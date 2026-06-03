import { clerkMiddleware } from '@clerk/nextjs/server';

// Pass-through — backend auth is disabled, Clerk is UI-only for user identity
export default clerkMiddleware();

export const config = {
  matcher: ['/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)'],
};
