import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { passengersApi } from "../../hooks/useApi";
import { NumberInput, Section } from "./FormControls";
import type { OwnerSettings, SettingsResponse } from "./types";

function LaneControl({ terminal, actual, canChange }: {
  terminal: string; actual: number; canChange: boolean;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<number | null>(null);
  const command = useRef<{ lanes: number; id: string } | null>(null);
  const mutation = useMutation({
    mutationFn: async () => {
      const lanes = draft ?? actual;
      // A failed HTTP response may follow a commit. Retry the same command ID.
      if (command.current?.lanes !== lanes) command.current = { lanes, id: crypto.randomUUID() };
      return passengersApi.setLanes(terminal, lanes, command.current.id);
    },
    onSuccess: () => {
      command.current = null;
      void client.invalidateQueries({ queryKey: ["sim-settings"] });
    },
  });
  return <div className="space-y-2 border-b border-gray-700 pb-3">
    <p>Terminal {terminal}: <strong>{actual} lanes applied</strong></p>
    <fieldset disabled={!canChange || mutation.isPending}>
      <NumberInput label={`Requested lanes — Terminal ${terminal}`} value={draft ?? actual}
        min={1} max={20} onChange={value => { setDraft(value); mutation.reset(); }} />
      <button className="btn-secondary mt-2" disabled={draft === null || draft === actual || !Number.isInteger(draft) || draft < 1 || draft > 20}
        onClick={() => mutation.mutate()}>
        {mutation.isPending ? "Awaiting owner…" : `Send Terminal ${terminal} lane command`}
      </button>
    </fieldset>
    {mutation.isSuccess && <p role="status">Owner acknowledged. Applied values refresh from the owner.</p>}
    {mutation.isError && <p role="alert">Lane command unconfirmed: {(mutation.error as Error).message}. Retry to confirm.</p>}
  </div>;
}

function ObservationTime({ owner }: { owner: OwnerSettings | undefined }) {
  return <p className="text-xs text-gray-400">Owner simulation time: {owner?.sim_time ?? "awaiting first clock tick"}</p>;
}

export function EffectiveSettings({ effective, canChange }: {
  effective: SettingsResponse["effective"]; canChange: boolean;
}) {
  const passenger = effective?.passenger;
  const baggage = effective?.baggage;
  return <section aria-label="Effective owner settings" className="space-y-3">
    <h2 className="text-xl font-bold">Effective owner settings</h2>
    <p className="text-gray-400">Observed from the owning services. Saved preferences do not confirm application.</p>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Section title="Security" icon="🔒">
        {passenger?.status === "available" && passenger.values ? <>
          <ObservationTime owner={passenger} />
          {"ABC".split("").map(terminal => <LaneControl key={terminal} terminal={terminal}
            actual={passenger.values![`lanes_${terminal.toLowerCase()}`]} canChange={canChange} />)}
          <p>MCT: {passenger.values.mct_minutes} min · configuration/restart required</p>
          {!canChange && <p>Lane commands require local operator access.</p>}
        </> : <p role="status">Passenger owner unavailable. Effective lanes and MCT unknown.</p>}
      </Section>
      <Section title="Baggage" icon="🧳">
        {baggage?.status === "available" && baggage.values ? <>
          <ObservationTime owner={baggage} />
          <p>Screening units: {baggage.values.screening_units}</p>
          <p>Sorting capacity: {baggage.values.sorting_capacity.toLocaleString()} bags/h</p>
          <p>DG false-positive rate: {baggage.values.dg_false_positive_rate}</p>
          <p className="text-gray-400">Nominal capacities. Changes require owner configuration/restart. Zone failures are shown in Baggage flow.</p>
        </> : <p role="status">Baggage owner unavailable. Effective capacities unknown.</p>}
      </Section>
    </div>
  </section>;
}
