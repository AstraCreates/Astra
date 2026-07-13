const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// The backend does not expose a separate Temporal/OTel viewer yet. Linking to
// the authenticated trace projection is still useful to operators, unlike the
// former inert "#" anchor: it returns the workflow, task queue, and trace IDs.
export default function RunTraceLink({ runId }: { runId: string }) {
  return (
    <a
      href={`${BASE}/runs/${encodeURIComponent(runId)}/trace`}
      target="_blank"
      rel="noreferrer"
      title="Open durable workflow and trace identifiers"
      className="pill"
      style={{ textDecoration: "none" }}
    >
      ⧉ View Trace
    </a>
  );
}
