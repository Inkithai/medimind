import { useState } from "react";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { Card, CardBody } from "../components/Card";
import { FacilityList } from "../components/FacilityList";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { MapPinIcon } from "../components/icons";
import { MapView } from "../components/MapView";
import { useAuth } from "../context/AuthContext";
import type { CareFacilitiesResponse, FacilityKind } from "../types/api";

const KINDS: { id: FacilityKind; label: string }[] = [
  { id: "any", label: "Any facility" },
  { id: "hospital", label: "Hospital" },
  { id: "clinic", label: "Clinic" },
  { id: "pharmacy", label: "Pharmacy" },
  { id: "laboratory", label: "Laboratory" },
];

export function FindCarePage() {
  const { credentials } = useAuth();
  const [location, setLocation] = useState("");
  const [kind, setKind] = useState<FacilityKind>("any");
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<CareFacilitiesResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  async function search() {
    const place = location.trim();
    if (place.length < 2) {
      setError(new Error("Enter a city, neighbourhood, or postcode."));
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const data = await api.searchFacilities(credentials, place, kind);
      setResult(data);
      setSelectedId(data.facilities[0]?.id ?? null);
    } catch (err) {
      setResult(null);
      setError(err);
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Find nearby facilities</h1>
        <p className="secondary-text mt-2 max-w-2xl">
          Optional directory lookup. MediMind does not recommend the best hospital. You choose a
          facility type and a place; a separate provider layer returns public listings.
        </p>
      </header>

      <Card>
        <CardBody className="grid gap-4 md:grid-cols-[1fr_12rem_auto] md:items-end">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">City or area</span>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void search();
                }
              }}
              placeholder="e.g. Kandy"
              className="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Facility type</span>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as FacilityKind)}
              className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm"
            >
              {KINDS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <button onClick={() => void search()} disabled={searching} className="btn-primary">
            <MapPinIcon className="h-5 w-5" />
            Search
          </button>
        </CardBody>
      </Card>

      {searching && <LoadingState label="Looking up public listings" />}
      {!searching && error !== null && <ErrorState error={error} onRetry={() => void search()} />}

      {!searching && result && (
        <>
          <Alert variant="warning" title="Not a referral">
            {result.disclaimer}
          </Alert>
          <p className="text-sm text-slate-600">
            {result.result_count} listing{result.result_count === 1 ? "" : "s"}
            {result.origin ? ` near ${result.origin.label}` : ""} · Provider: {result.provider}
          </p>
          {result.result_count === 0 ? (
            <Card>
              <CardBody className="py-10 text-center text-sm text-slate-600">
                No public listings in that area. Try a nearby city.
              </CardBody>
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
              <FacilityList facilities={result.facilities} selectedId={selectedId} onSelect={setSelectedId} />
              <MapView
                originLabel={result.origin?.label}
                facilities={result.facilities}
                selectedId={selectedId}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
