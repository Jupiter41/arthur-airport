# Understanding Airport Costs

How Arthur International Airport tracks, calculates, and helps you manage operational costs.

---

## What the Cost Dashboard Shows

The **Cost Dashboard** gives you a live financial picture of the airport. As flights land, depart,
get delayed, or experience incidents, the system automatically calculates associated costs and
revenues. Everything updates in real-time as the simulation progresses.

You'll see:

- **Total costs** — what the airport spends to operate
- **Total revenue** — what the airport earns from airlines and passengers
- **Net P&L** — profit or loss (revenue minus costs)
- **EU261 exposure** — potential compensation owed to passengers for delays

---

## Cost Categories

### Costs the airport incurs

| Category               | When it happens                   | How it's calculated                                          |
| ---------------------- | --------------------------------- | ------------------------------------------------------------ |
| **Landing fees**       | A flight arrives at the gate      | Aircraft weight × €12 per tonne                              |
| **Gate fees**          | A flight releases its gate        | Time at gate × €150 per hour                                 |
| **Passenger fees**     | A flight departs                  | Number of passengers × €12 each                              |
| **EU261 compensation** | A flight is delayed 3+ hours      | €250–€600 per passenger depending on distance                |
| **Holding fuel**       | Aircraft circling waiting to land | Fuel burn rate × time × €0.90/kg                             |
| **Ground handling**    | A flight arrives                  | Pushback + catering + cleaning + baggage loading             |
| **Incident costs**     | An incident occurs                | Fixed cost per incident type (€8K–€80K)                      |
| **Staffing**           | Every hour                        | Staff count × hourly rate (security, check-in, gate, ground) |

### Revenue the airport earns

| Category                  | When it happens                           | How it's calculated                         |
| ------------------------- | ----------------------------------------- | ------------------------------------------- |
| **Landing fee revenue**   | Same as landing fee cost                  | Same calculation (airlines pay the airport) |
| **Passenger fee revenue** | Same as passenger fee cost                | Airlines pass through the fee               |
| **Retail revenue**        | Continuously while passengers are airside | €12 per passenger per hour                  |
| **Slot fee revenue**      | A flight departs                          | €2,000 per departure slot                   |

> **Note:** Landing and passenger fees appear both as costs (airline perspective) and revenue
> (airport perspective). The dashboard shows both sides.

---

## How Financial Recommendations Work

The system watches your running costs and automatically suggests actions when thresholds are exceeded:

| Situation                   | Recommendation        | Logic                                        |
| --------------------------- | --------------------- | -------------------------------------------- |
| EU261 exposure > €10,000    | Open a security lane  | Reduces delays → lowers compensation risk    |
| Holding fuel costs > €5,000 | Ground delay program  | Keeps aircraft on ground → saves fuel        |
| Ground handling > €50,000   | Reassign gates        | Shorter walks → faster turnarounds           |
| Total costs > €100,000      | Open make-up carousel | Speeds up baggage → fewer missed connections |

Each recommendation includes:

- **Cost** — what it would take to implement
- **Saving** — expected reduction in costs
- **Net benefit** — saving minus cost
- **Confidence** — how certain the system is (50–100%)
- **Payback** — how quickly the action pays for itself

---

## How to Edit Cost Rates

### Using Preset Profiles

The easiest way to change cost parameters. On the Cost Dashboard, expand the
**Cost Rate Configuration** panel and select a profile:

| Profile                   | Description                                     |
| ------------------------- | ----------------------------------------------- |
| **Default (Eurocontrol)** | Standard rates based on European reference data |
| **Low-Cost Hub**          | Reduced fees typical of budget airline airports |
| **Premium Hub**           | Higher fees and retail revenue for a major hub  |
| **High Incident Cost**    | Elevated incident costs for stress-testing      |

Click **Apply** and the new rates take effect immediately for all future cost calculations.

### Custom Editing

Switch to the **Custom Editor** tab to modify individual values:

1. Expand the **Cost Rate Configuration** section
2. Click **Custom Editor**
3. Adjust any field — modified fields highlight in blue
4. Click **Apply Custom Rates**

Changes take effect immediately. Past cost records are not recalculated — only new events
use the updated rates.

### Programmatic Access

You can also update rates via the REST API:

```bash
curl -X PATCH http://localhost:3000/api/v1/costs/rates \
  -H "Content-Type: application/json" \
  -d '{"airport_fees": {"landing_rate_per_tonne_eur": 15.0}}'
```

The API uses deep merge — you only need to send the fields you want to change.

---

## Example: Impact of a Delay

Imagine flight BA417 (Boeing 777, 300 passengers) is delayed 3 hours and 20 minutes:

1. **Holding fuel**: 6,000 kg/hour × 3.3 hours × €0.90/kg = **€17,820**
2. **Crew overtime**: 10 crew × €200/hour × 3.3 hours = **€6,600**
3. **EU261 compensation**: 300 pax × €600 (long-haul, 3h+ delay) = **€180,000**
4. **Extra gate time**: 3.3 extra hours × €150/hour = **€495**

**Total impact of one delayed wide-body flight: ~€205,000**

This is why the system recommends preventive actions when EU261 exposure starts climbing.

---

## Architecture (for developers)

The cost-service is a passive Kafka consumer that:

1. Listens to flight events, incident events, and simulation clock ticks
2. Calculates costs based on the rate table
3. Writes `CostRecord` nodes to Neo4j
4. Emits `CostRecorded` events to Kafka
5. The dashboard queries the REST API every 10–15 seconds

```
flights.events  ──┐
incidents.events ─┤──→  cost-service  ──→  Neo4j (CostRecord nodes)
sim.clock  ───────┘                   ──→  cost.events (Kafka)
                                      ──→  REST API → Dashboard
```

For full technical details, see `docs/services/cost-service/SPEC.md`.
