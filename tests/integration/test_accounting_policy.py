"""Real Neo4j/Kafka validation of airport accounting and planning semantics."""

import os
from pathlib import Path
import subprocess

import pytest

from tests.integration.test_financial_ledger import isolated_financial_worker  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]

COST_CHECK = r'''
import asyncio, json
from uuid import uuid4
from db import neo4j as db, queries
from services import ledger, cost_engine, valuation
from kafka import producer
from routers.costs import cost_summary, get_pnl, get_hourly_curve

async def run():
    await db.wait_for_neo4j(max_attempts=1)
    await ledger.initialize()
    original_day = cost_engine.get_running_totals()['sim_day']
    day = 700000 + int(uuid4().hex[:5], 16)
    fid, tid = 'synthetic-g2-' + str(uuid4()), 'synthetic-g2-' + str(uuid4())
    clock = '2026-01-01T12:00:00Z'
    async with db.get_driver().session() as session:
        await (await session.run('CREATE (:Flight {id: $fid}), (:Terminal {id: $tid})', fid=fid, tid=tid)).consume()
    rows = [('landing_fee', 1000, False), ('landing_fee', 1000, True),
            ('staffing', 300, False), ('eu261_compensation', 25000, False)]
    async def charge(envelope):
        for category, amount, revenue in rows:
            await cost_engine._write_and_emit(dict(id=str(uuid4()), category=category,
                amount_eur=amount, is_revenue=revenue, sim_time=clock, sim_day=day,
                description='Synthetic G2 validation'), flight_id=fid, terminal_id=tid)
    async def no_effects(envelope):
        pass
    event = dict(event_id=str(uuid4()), event_type='SimClockTick', sim_time=clock,
                 payload={'day_of_sim': day})
    try:
        assert await ledger.process(event, charge)
        assert not await ledger.process(event, charge)
        summary = await cost_summary()
        assert summary['total_cost_eur'] == 300
        assert summary['net_eur'] == 700
        assert summary['airline_cost_eur'] == 26000
        pnl = await queries.daily_pnl(db.get_driver(), day)
        assert pnl['total_cost_eur'] == 300 and pnl['net_eur'] == 700
        assert (await get_pnl(day))['by_category'] == {'staffing': 300}
        flight = await queries.flight_cost_breakdown(db.get_driver(), fid)
        terminal = await queries.terminal_pnl(db.get_driver(), tid, day)
        assert flight['airline_cost_eur'] == terminal['airline_cost_eur'] == 26000
        assert flight['net_eur'] == terminal['net_eur'] == 700
        hourly = await get_hourly_curve(day)
        assert hourly['hours'][12]['cost_eur'] == 300
        assert hourly['hours'][12]['airline_cost_eur'] == 26000
        assert (await queries.daily_pnl(db.get_driver(), day))['net_eur'] == 700
        assert valuation.build_ebitda(pnl)['ebitda']['daily_eur'] == 700
        # Simulate an old mixed checkpoint and capture migration fact inside
        # the same transaction, before the normal publisher can drain it.
        async def migrate(tx):
            row = await (await tx.run("MATCH (s:CostRuntime {id: 'latest'}) RETURN s.document AS document")).single()
            state = json.loads(row['document'])
            state.pop('accounting_policy')
            state['days'][str(day)]['cost']['total_cost_eur'] = 999999
            await (await tx.run("MATCH (s:CostRuntime {id: 'latest'}) SET s.document = $document",
                document=json.dumps(state))).consume()
            restored, revision = await ledger._locked_state(tx)
            row = await (await tx.run('MATCH (e:CostOutbox {revision: $revision}) RETURN e.document AS document', revision=revision)).single()
            return restored, json.loads(row['document'])
        async with db.get_driver().session() as session:
            restored, fact = await session.execute_write(migrate)
        assert restored['days'][str(day)]['cost']['net_eur'] == 700
        assert fact['event_type'] == 'FinancialAccountingUpdated'
        producer.init_kafka_producer()
        try:
            producer.publish_confirmed(fact)
            producer.publish_confirmed(fact)  # stable-ID redelivery accepted
        finally:
            producer.close_kafka_producer()
        await ledger.initialize()
        assert cost_engine.get_running_totals()['net_eur'] == 700
        print('G2 live accounting: reports, replay, migration, restart and Kafka acknowledgement passed')
    finally:
        await ledger.process(dict(event_id=str(uuid4()), event_type='SimClockTick',
            sim_time=clock, payload={'day_of_sim': original_day}), no_effects)
        async def cleanup(tx):
            state, _ = await ledger._locked_state(tx)
            await (await tx.run('MATCH (c:CostRecord {sim_day: $day}) DETACH DELETE c', day=day)).consume()
            await (await tx.run('MATCH (f:Flight {id:$id}) DETACH DELETE f', id=fid)).consume()
            await (await tx.run('MATCH (t:Terminal {id:$id}) DETACH DELETE t', id=tid)).consume()
            state['days'].pop(str(day), None)
            await (await tx.run("MATCH (s:CostRuntime {id: 'latest'}) SET s.document = $document",
                document=json.dumps(state))).consume()
        async with db.get_driver().session() as session:
            await session.execute_write(cleanup)
        await db.close_neo4j()
asyncio.run(run())
'''

PLANNING_CHECK = r'''
from datetime import date
from uuid import uuid4
from adapters.simulation import SimulationAdapter
from engine.simulation import PlanningSimEngine
from engine.infrastructure import InfrastructureConfig
from engine.results import ScenarioResults, KPIDistribution as KPI
from finance.benefit_extractor import extract_annual_benefit
from db import store
from scenarios.model import get_results
from _common.financial_rates import load_default_rates
rates = load_default_rates()
assert PlanningSimEngine._compute_eu261(180, 1200, 101, rates) == 25250
engine = PlanningSimEngine(adapter=SimulationAdapter(), seed=0, financial_rates=rates)
result = engine.run_day(date(2026, 1, 1), InfrastructureConfig(daily_flight_target=10))
assert result.net_eur == result.total_revenue_eur - result.total_cost_eur
assert result.airline_cost_eur > 0
benefit = extract_annual_benefit(
    {'eu261_liability_eur': KPI(mean=25000), 'total_cost_eur': KPI(mean=300), 'total_revenue_eur': KPI(mean=1000)},
    {'eu261_liability_eur': KPI(mean=0), 'total_cost_eur': KPI(mean=400), 'total_revenue_eur': KPI(mean=900)},
    operating_days_per_year=10, financial_rates=rates)
assert benefit.total_annual_benefit == -2000
store.initialize()
try:
    repository = store.get_repository()
    sid = 'synthetic-g2-' + str(uuid4())
    repository.put('PlanningResult', sid, {'financials': {'npv_eur': 123}})
    assert get_results(sid)['accounting_policy'] == 'legacy-mixed'
    assert get_results(sid)['financials']['npv_eur'] == 123
    repository.put('PlanningResult', sid, ScenarioResults(scenario_id=sid).to_dict())
    assert get_results(sid)['accounting_policy'] == 'airport-v1'
    repository.delete('PlanningResult', sid)
finally:
    store.close()
print('G2 live planning: fees, full liability, airport-only benefits and legacy result labels passed')
'''


@pytest.mark.parametrize('service,source', [('cost-service', COST_CHECK), ('planning-service', PLANNING_CHECK)], ids=['cost', 'planning'])
def test_accounting_policy_against_local_stack(service, source):
    # COMPOSE_PROJECT_NAME/COMPOSE_FILE allow an isolated local stack; CI uses
    # its already running full stack. No skips certify this accounting gate.
    # Reuse the ledger gate's module fixture: its normal consumer/outbox is
    # stopped while these independent migration/restart workers own the clock.
    result = subprocess.run(['docker', 'compose', 'run', '--rm', '-T', '--no-deps', service, 'python', '-c', source],
                            cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
