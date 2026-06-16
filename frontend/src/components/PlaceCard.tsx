import Image from "next/image";
import { MapPin, Star, ExternalLink } from "lucide-react";
import { ChatPlace } from "@/types/chat";

const CATEGORY_COLORS: Record<string, string> = {
  attraction: "bg-sky-100 text-sky-700 dark:bg-sky-900 dark:text-sky-300",
  restaurant: "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300",
  hotel: "bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300",
};

interface PlaceCardProps {
  place: ChatPlace;
}

export default function PlaceCard({ place }: PlaceCardProps) {
  const badgeClass = CATEGORY_COLORS[place.category] ?? "bg-zinc-100 text-zinc-700";

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm transition-shadow hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900">
      <div className="relative h-48 w-full bg-zinc-100 dark:bg-zinc-800">
        {place.image_url ? (
          <Image
            src={place.image_url}
            alt={place.name}
            fill
            className="object-cover"
            sizes="(max-width: 768px) 100vw, 33vw"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-zinc-400 dark:text-zinc-600">
            <MapPin size={40} />
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold leading-tight text-zinc-900 dark:text-zinc-100">
            {place.name}
          </h3>
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${badgeClass}`}>
            {place.category}
          </span>
        </div>
        {place.rating !== null && (
          <div className="flex items-center gap-1 text-amber-500">
            <Star size={13} fill="currentColor" />
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{place.rating.toFixed(1)}</span>
          </div>
        )}
        <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">{place.address}</p>
        {place.description && (
          <p className="mt-auto text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{place.description}</p>
        )}
        {place.source_url && (
          <a
            href={place.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            View details <ExternalLink size={11} />
          </a>
        )}
      </div>
    </div>
  );
}
