const AUTH_FLAG_KEY = "authenticated";

export const setAuthFlag = () => localStorage.setItem(AUTH_FLAG_KEY, "1");
export const clearAuthFlag = () => localStorage.removeItem(AUTH_FLAG_KEY);
export const hasAuthFlag = () => localStorage.getItem(AUTH_FLAG_KEY) === "1";
