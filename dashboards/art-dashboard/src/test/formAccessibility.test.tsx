import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NumberInput, SelectInput, Toggle } from "../pages/Settings/FormControls";
import { HourlyWeightsEditor } from "../pages/Settings/HourlyWeightsEditor";

afterEach(cleanup);
it("associates visible setting labels with unique controls and exposes units", () => {
  render(<>
    <NumberInput label="Capacity" value={4} min={1} max={20} unit="pax" onChange={() => {}} />
    <NumberInput label="Capacity" value={5} min={1} max={20} unit="pax" onChange={() => {}} />
    <SelectInput label="Weather" value="simulated" options={[{value:"simulated",label:"Simulated"}]} onChange={() => {}} />
  </>);
  const inputs = screen.getAllByRole("spinbutton", {name:"Capacity (pax)"});
  expect(inputs[0].id).not.toBe(inputs[1].id);
  expect(screen.getByRole("combobox", {name:"Weather"})).toBeInTheDocument();
});
it("exposes switch identity, current state and activation", () => {
  const change = vi.fn();
  render(<Toggle label="Auto weather" checked={true} onChange={change} />);
  const toggle = screen.getByRole("switch", {name:"Auto weather", checked:true});
  fireEvent.click(toggle);
  expect(change).toHaveBeenCalledWith(false);
});
it("names every hourly slider for keyboard adjustment", () => {
  render(<HourlyWeightsEditor weights={{}} onChange={() => {}} />);
  const sliders = screen.getAllByRole("slider");
  expect(sliders.length).toBeGreaterThan(0);
  expect(sliders.every(slider => /Departure weight at \d{2}:00/.test(slider.getAttribute("aria-label") ?? ""))).toBe(true);
});
