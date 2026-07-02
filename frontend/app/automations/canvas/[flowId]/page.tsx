import AutomationCanvas from "@/components/AutomationCanvas";

export default async function AutomationCanvasRoute({ params }: { params: Promise<{ flowId: string }> }) {
  const { flowId } = await params;
  return <AutomationCanvas flowId={flowId} />;
}
