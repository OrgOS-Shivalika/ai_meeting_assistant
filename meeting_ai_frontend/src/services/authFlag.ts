const AUTH_FLAG_KEY = "authenticated";

// The flag mirrors the auth cookie for the route guard's benefit, so it has to
// share the cookie's LIFETIME too. "Keep me signed in" unchecked gets a
// session cookie that dies with the browser; a localStorage flag would outlive
// it and the guard would wave the next visit straight into the app, which then
// 401s and bounces to /login. sessionStorage dies at the same moment the
// cookie does, so the two stay in step.
export const setAuthFlag = (persist = true) => {
  clearAuthFlag();
  (persist ? localStorage : sessionStorage).setItem(AUTH_FLAG_KEY, "1");
};

// Clear BOTH — which store was used depends on a choice made at login, and
// logout must not leave the other one behind.
export const clearAuthFlag = () => {
  localStorage.removeItem(AUTH_FLAG_KEY);
  sessionStorage.removeItem(AUTH_FLAG_KEY);
};

export const hasAuthFlag = () =>
  localStorage.getItem(AUTH_FLAG_KEY) === "1" ||
  sessionStorage.getItem(AUTH_FLAG_KEY) === "1";
