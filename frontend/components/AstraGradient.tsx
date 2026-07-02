export default function AstraGradient() {
  return (
    <div
      aria-hidden="true"
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        background: [
          "radial-gradient(circle at 18% 22%, rgba(124,255,230,0.22), transparent 0 26%)",
          "radial-gradient(circle at 78% 18%, rgba(255,255,255,0.18), transparent 0 22%)",
          "radial-gradient(circle at 62% 82%, rgba(93,149,255,0.24), transparent 0 28%)",
          "linear-gradient(135deg, #002eff 0%, #1847ff 34%, #4d79ff 58%, #c9fff4 100%)",
        ].join(", "),
      }}
    />
  );
}
