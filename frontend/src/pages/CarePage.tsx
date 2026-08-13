import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { CareMap } from "../components/CareMap";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState, Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { MapPinIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type {
  CareDay,
  CarePlace,
  CareSearchResponse,
  CareSuggestion,
  CareTimeOfDay,
} from "../types/api";
import { classNames } from "../utils/format";

const DAY_OPTIONS: { id: CareDay; label: string }[] = [
  { id: "mon", label: "Mon" },
  { id: "tue", label: "Tue" },
  { id: "wed", label: "Wed" },
  { id: "thu", label: "Thu" },
  { id: "fri", label: "Fri" },
  { id: "sat", label: "Sat" },
  { id: "sun", label: "Sun" },
];

const TIME_OPTIONS: { id: CareTimeOfDay; label: string }[] = [
  { id: "any", label: "Any time" },
  { id: "morning", label: "Morning" },
  { id: "afternoon", label: "Afternoon" },
  { id: "evening", label: "Evening" },
];

export function CarePage() {
  const { credentials } = useAuth();
  const [suggestion, setSuggestion] = useState<CareSuggestion | null>(null);
  const [suggestError, setSuggestError] = useState<unknown>(null);
  const [suggesting, setSuggesting] = useState(true);

  const [city, setCity] = useState("");
  const [specialty, setSpecialty] = useState("general_practice");
  const [days, setDays] = useState<CareDay[]>(["mon", "tue", "wed", "thu", "fri"]);
  const [timeOfDay, setTimeOfDay] = useState<CareTimeOfDay>("any");
  const [radiusKm, setRadiusKm] = useState(8);

  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<unknown>(null);
  const [result, setResult] = useState<CareSearchResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [onlySpecialty, setOnlySpecialty] = useState(false);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [onlyPhone, setOnlyPhone] = useState(false);

  useStrictEffect(() => {
    setSuggesting(true);
    api
      .getCareSuggestion(credentials)
      .then((data) => {
        setSuggestion(data);
        setSpecialty(data.suggested.id);
        setSuggestError(null);
      })
      .catch((err) => {
        setSuggestError(err);
      })
      .finally(() => setSuggesting(false));
  }, [credentials]);

  async function search() {
    const place = city.trim();
    if (place.length < 2) {
      setSearchError(new Error("Enter a city, neighbourhood, or postcode."));
      return;
    }
    if (days.length === 0) {
      setSearchError(new Error("Pick at least one day you could attend."));
      return;
    }
    setSearching(true);
    setSearchError(null);
    try {
      const data = await api.searchCare(credentials, {
        city: place,
        specialty,
        days,
        time_of_day: timeOfDay,
        radius_km: radiusKm,
      });
      setResult(data);
      setSelectedId(data.results[0]?.id ?? null);
    } catch (err) {
      setResult(null);
      setSearchError(err);
    } finally {
      setSearching(false);
    }
  }

  const filtered = useMemo(() => {
    if (!result) return [];
    return result.results.filter((place) => {
      if (onlySpecialty && place.match_kind !== "specialty") return false;
      if (onlyOpen && place.availability !== "open") return false;
      if (onlyPhone && !place.phone) return false;
      return true;
    });
  }, [result, onlySpecialty, onlyOpen, onlyPhone]);

  const selected = filtered.find((place) => place.id === selectedId) || filtered[0] || null;

  function toggleDay(day: CareDay) {
    setDays((current) => (current.includes(day) ? current.filter((item) => item !== day) : [...current, day]));
  }

  const specialties = suggestion?.all || [{ id: "general_practice", label: "General practice" }];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Find care nearby</h1>
        <p className="secondary-text mt-2 max-w-2xl">
          We suggest a specialty from your records, then search real clinics on OpenStreetMap near the
          city you type. This is a public directory, not a booking or a referral.
        </p>
      </header>

      {suggesting && <LoadingState label="Reading your records for a specialty suggestion" />}
      {!suggesting && suggestError !== null && (
        <ErrorState error={suggestError} onRetry={() => window.location.reload()} />
      )}

      {!suggesting && suggestion && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
              <MapPinIcon className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900">
                Suggested specialty: {suggestion.suggested.label}
              </p>
              {suggestion.has_records ? (
                <ul className="mt-1 space-y-0.5 text-sm text-slate-600">
                  {suggestion.suggested.reasons?.map((reason) => (
                    <li key={reason}>• {reason}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-sm text-slate-600">
                  Upload records for a more specific suggestion.{" "}
                  <Link to="/upload" className="font-medium text-brand-600 hover:text-brand-700">
                    Upload a document
                  </Link>
                </p>
              )}
              {suggestion.alternatives.length > 0 && (
                <p className="mt-2 text-xs text-slate-500">
                  Also consider: {suggestion.alternatives.map((item) => item.label).join(" · ")}
                </p>
              )}
            </div>
          </div>
        </section>
      )}

      <Card>
        <CardBody className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Your city or area</span>
              <input
                value={city}
                onChange={(e) => setCity(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void search();
                  }
                }}
                placeholder="e.g. Kandy, Colombo 07, 20000"
                className="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Specialty</span>
              <select
                value={specialty}
                onChange={(e) => setSpecialty(e.target.value)}
                className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                {specialties.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div>
            <p className="text-sm font-medium text-slate-700">Days you could attend</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {DAY_OPTIONS.map((day) => {
                const on = days.includes(day.id);
                return (
                  <button
                    key={day.id}
                    type="button"
                    onClick={() => toggleDay(day.id)}
                    className={classNames(
                      "min-h-[40px] rounded-full px-3 text-sm font-medium ring-1",
                      on
                        ? "bg-brand-600 text-white ring-brand-600"
                        : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"
                    )}
                  >
                    {day.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Time of day</span>
              <select
                value={timeOfDay}
                onChange={(e) => setTimeOfDay(e.target.value as CareTimeOfDay)}
                className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                {TIME_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Search radius: {radiusKm} km</span>
              <input
                type="range"
                min={2}
                max={30}
                value={radiusKm}
                onChange={(e) => setRadiusKm(parseInt(e.target.value, 10))}
                className="mt-3 w-full"
              />
            </label>
            <button onClick={() => void search()} disabled={searching} className="btn-primary">
              {searching ? <Spinner className="h-5 w-5" /> : <MapPinIcon className="h-5 w-5" />}
              Search clinics
            </button>
          </div>
        </CardBody>
      </Card>

      {searching && <LoadingState label="Looking up clinics on OpenStreetMap" />}
      {!searching && searchError !== null && <ErrorState error={searchError} onRetry={() => void search()} />}

      {!searching && result && (
        <>
          <Alert variant="warning" title="Not a referral">
            {result.disclaimer}
          </Alert>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-600">
              {result.result_count === 0
                ? "No mapped clinics in this area"
                : `${result.result_count} place${result.result_count === 1 ? "" : "s"} near ${result.location.label}`}
              {" · "}
              <a
                href={result.source.url}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-brand-600 hover:text-brand-700"
              >
                {result.source.attribution}
              </a>
            </p>
            {result.result_count > 0 && (
              <div className="flex flex-wrap gap-2 text-xs">
                <FilterChip label="Specialty match" on={onlySpecialty} onToggle={() => setOnlySpecialty((v) => !v)} />
                <FilterChip label="Open in my window" on={onlyOpen} onToggle={() => setOnlyOpen((v) => !v)} />
                <FilterChip label="Has a phone" on={onlyPhone} onToggle={() => setOnlyPhone((v) => !v)} />
              </div>
            )}
          </div>

          {result.result_count === 0 ? (
            <Card>
              <CardBody className="py-12 text-center">
                <p className="text-base font-semibold text-slate-800">No clinics found</p>
                <p className="secondary-text mx-auto mt-2 max-w-lg">{result.zero_results_hint}</p>
                <p className="mt-3 text-xs text-slate-400">Source: {result.source.name} · {result.source.license}</p>
              </CardBody>
            </Card>
          ) : filtered.length === 0 ? (
            <Card>
              <CardBody className="py-10 text-center">
                <p className="text-sm font-semibold text-slate-800">Nothing matches those filters</p>
                <p className="secondary-text mt-1">Turn a filter off to see the other {result.result_count} result(s).</p>
              </CardBody>
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
              <ul className="max-h-[640px] space-y-2 overflow-y-auto pr-1 scroll-thin">
                {filtered.map((place) => (
                  <li key={place.id}>
                    <PlaceCard
                      place={place}
                      selected={selected?.id === place.id}
                      onSelect={() => setSelectedId(place.id)}
                    />
                  </li>
                ))}
              </ul>
              <div className="lg:sticky lg:top-6 lg:self-start">
                <CareMap
                  center={{ lat: result.location.lat, lon: result.location.lon }}
                  places={filtered}
                  selectedId={selected?.id ?? null}
                  onSelect={setSelectedId}
                />
                {selected && (
                  <p className="secondary-text mt-2">
                    Selected: <span className="font-medium text-slate-700">{selected.name}</span> ·{" "}
                    <a href={selected.source_url} target="_blank" rel="noreferrer" className="text-brand-600">
                      View on OpenStreetMap
                    </a>
                  </p>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {!result && !searching && !searchError && (
        <Card>
          <CardBody className="flex flex-col items-center gap-2 py-10 text-center">
            <UploadIcon className="h-8 w-8 text-slate-300" />
            <p className="text-sm font-medium text-slate-700">Enter a city to see real clinics on the map</p>
            <p className="secondary-text max-w-md">
              Results come from OpenStreetMap volunteers. Coverage is better in cities than in small towns.
            </p>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function FilterChip({ label, on, onToggle }: { label: string; on: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={classNames(
        "rounded-full px-3 py-1.5 font-medium ring-1",
        on ? "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-600 ring-slate-200"
      )}
    >
      {label}
    </button>
  );
}

function PlaceCard({
  place,
  selected,
  onSelect,
}: {
  place: CarePlace;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={classNames(
        "w-full rounded-xl border bg-white p-4 text-left shadow-sm transition",
        selected ? "border-brand-300 ring-2 ring-brand-100" : "border-slate-200 hover:border-brand-200"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{place.name}</p>
          <p className="mt-0.5 text-xs capitalize text-slate-500">
            {place.place_type}
            {place.specialties.length > 0 ? ` · ${place.specialties.join(", ")}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <StatusBadge
            tone={
              place.match_kind === "specialty" ? "brand" : place.match_kind === "hospital" ? "warning" : "neutral"
            }
          >
            {place.match_kind === "specialty"
              ? "Specialty match"
              : place.match_kind === "hospital"
              ? "Hospital"
              : place.match_kind === "general"
              ? "General"
              : "Other"}
          </StatusBadge>
          <StatusBadge
            tone={place.availability === "open" ? "success" : place.availability === "closed" ? "danger" : "neutral"}
          >
            {place.availability === "open"
              ? "Open in your window"
              : place.availability === "closed"
              ? "Closed then"
              : "Hours unknown"}
          </StatusBadge>
        </div>
      </div>
      <p className="mt-2 text-xs text-slate-600">{place.address || "Address not mapped"}</p>
      <p className="mt-1 text-xs text-slate-500">
        {place.distance_km} km
        {place.phone ? ` · ${place.phone}` : ""}
        {place.opening_hours ? ` · ${place.opening_hours}` : ""}
      </p>
      <div className="mt-2 flex flex-wrap gap-3 text-xs font-medium">
        {place.phone && (
          <a href={`tel:${place.phone}`} className="text-brand-600 hover:text-brand-700" onClick={(e) => e.stopPropagation()}>
            Call
          </a>
        )}
        {place.website && (
          <a
            href={place.website}
            target="_blank"
            rel="noreferrer"
            className="text-brand-600 hover:text-brand-700"
            onClick={(e) => e.stopPropagation()}
          >
            Website
          </a>
        )}
        <a
          href={place.source_url}
          target="_blank"
          rel="noreferrer"
          className="text-slate-500 hover:text-slate-700"
          onClick={(e) => e.stopPropagation()}
        >
          OSM source
        </a>
      </div>
    </button>
  );
}
