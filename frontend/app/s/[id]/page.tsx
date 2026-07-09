import { Suspense } from "react";
import SessionRoute from "@/components/SessionRoute";

export default async function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  return (
    <Suspense>
      <SessionRoute sessionId={id} />
    </Suspense>
  );
}
