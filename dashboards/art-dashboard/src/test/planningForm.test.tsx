import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CustomForm } from "../pages/Planning/components/ScenarioBuilder";

afterEach(cleanup);
it("accepts owner cost estimates that are not multiples of 1000 euros", () => {
  render(<CustomForm
    form={{name:"Synthetic experiment",description:"",horizon:"day",monte_carlo_runs:2,
      demand_source:"simulation",capex_eur:0,opex_delta_eur:0,years_horizon:25,discount_rate:0.07}}
    setForm={() => {}} infraDeltas={{gates:{A:0,B:0,C:0},security_lanes:{A:0,B:1,C:0},screening_units:0,runways:0}}
    setInfraDeltas={() => {}} hasInfraChanges={true}
    costEstimate={{breakdown:[],total_capex_eur:123456.78,total_annual_opex_eur:204400}}
    baselineGates={{A:14,B:14,C:14}} baselineSecurity={{A:4,B:3,C:4}}
    baselineScreening={6} baselineRunways={2} isPending={false} onSubmit={event => event.preventDefault()}
  />);
  const opex = screen.getByRole("spinbutton", {name:/Annual OPEX delta/}) as HTMLInputElement;
  const capex = screen.getByRole("spinbutton", {name:/CAPEX/}) as HTMLInputElement;
  expect(opex.value).toBe("204400");
  expect(capex.value).toBe("123456.78");
  expect(opex.validity.stepMismatch).toBe(false);
  expect(capex.validity.stepMismatch).toBe(false);
  expect(opex.closest("form")!.checkValidity()).toBe(true);
});
