// Shared mutable ref — StarGuide writes, SpaceEnv reads each frame.
// Using a plain object (not React state) to avoid re-renders.
export const starPos = { x: -9999, y: -9999 };
