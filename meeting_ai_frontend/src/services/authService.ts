import { apiClient } from "./apiClient";
import { clearCurrentUser } from "../features/auth/hooks/useCurrentUser";

export const authService = {
  async login(credentials: any) {
    clearCurrentUser();
    const data = await apiClient("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
    });
    if (data.access_token) {
      localStorage.setItem("token", data.access_token);
    }
    return data;
  },

  async register(userData: any) {
    return apiClient("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(userData),
    });
  },

  logout() {
    localStorage.removeItem("token");
    clearCurrentUser();
  },

  getToken() {
    return localStorage.getItem("token");
  },

  isAuthenticated() {
    return !!this.getToken();
  },

  async getGoogleAuthUrl() {
    return apiClient("/auth/google/login");
  }
};
