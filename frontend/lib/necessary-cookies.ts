export const COOKIE_NOTICE_NAME = "astra_cookie_notice";
export const COOKIE_NOTICE_VALUE = "acknowledged";
export const COOKIE_NOTICE_MAX_AGE_SECONDS = 60 * 60 * 24 * 180;

export const NECESSARY_COOKIES = [
  {
    name: COOKIE_NOTICE_NAME,
    purpose: "Remembers that the necessary-cookie notice was acknowledged.",
    duration: "180 days",
  },
  {
    name: "authjs.session-token",
    purpose: "Maintains authentication, session security, and account access.",
    duration: "Managed by NextAuth based on session state.",
  },
];
