"use client";

export default function Skeleton({
  width = "100%",
  height = 16,
  radius = 8,
}: {
  width?: number | string;
  height?: number;
  radius?: number;
}) {
  return (
    <>
      <style>{`@keyframes astra-skeleton { 0% { opacity: .52; } 50% { opacity: 1; } 100% { opacity: .52; } }`}</style>
      <div
        style={{
          width,
          height,
          borderRadius: radius,
          background: "color-mix(in srgb, var(--text-3) 12%, transparent)",
          animation: "astra-skeleton 1.2s ease-in-out infinite",
        }}
      />
    </>
  );
}
