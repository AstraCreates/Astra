export function isCurrentCopilotTurn(activeTurnId: string, eventTurnId: unknown): boolean {
  return Boolean(activeTurnId) && activeTurnId === String(eventTurnId || "");
}
