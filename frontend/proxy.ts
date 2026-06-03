import { clerkMiddleware } from '@clerk/nextjs/server';

// Pass-through — no server-side auth enforcement, Clerk is UI-only
export default clerkMiddleware();

export const config = {
  matcher: ['/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)'],
};
