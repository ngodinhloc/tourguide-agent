import ReactMarkdown from "react-markdown";
import PlaceCard from "./PlaceCard";
import { ChatResult } from "@/types/chat";

interface ResultsPanelProps {
  result: ChatResult;
}

const CATEGORY_ORDER = ["attraction", "restaurant", "hotel"];
const CATEGORY_LABELS: Record<string, string> = {
  attraction: "Top Attractions",
  restaurant: "Food & Restaurants",
  hotel: "Where to Stay",
};

export default function ResultsPanel({ result }: ResultsPanelProps) {
  const grouped = CATEGORY_ORDER.reduce<Record<string, ChatResult["places"]>>(
    (acc, cat) => {
      acc[cat] = result.places.filter((p) => p.category === cat);
      return acc;
    },
    {}
  );

  return (
    <div className="w-full max-w-5xl space-y-10">
      <div>
        <h1 className="mb-4 text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
          {result.location}
        </h1>
        <div className="prose prose-zinc max-w-none text-sm leading-7 dark:prose-invert">
          <ReactMarkdown>{result.narrative}</ReactMarkdown>
        </div>
      </div>

      {CATEGORY_ORDER.map((cat) => {
        const places = grouped[cat];
        if (!places?.length) return null;
        return (
          <section key={cat}>
            <h2 className="mb-4 text-xl font-semibold text-zinc-800 dark:text-zinc-200">
              {CATEGORY_LABELS[cat]}
            </h2>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {places.map((place) => (
                <PlaceCard key={`${place.name}-${place.address}`} place={place} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
