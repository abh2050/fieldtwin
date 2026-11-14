import { createContext, useContext, useState, type ReactNode } from "react";
import { getToken, setToken } from "./api";

// Locally the API issues bearer tokens from FIELDTWIN_API_TOKENS (`make app-tokens`). The role a token
// carries is enforced by the API and again by the database; the app only uses it to explain why an
// action is unavailable.
type Auth = { token: string | null; signIn: (token: string) => void; signOut: () => void };

const AuthContext = createContext<Auth>({ token: null, signIn: () => {}, signOut: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, set] = useState<string | null>(getToken());
  const value: Auth = {
    token,
    signIn: (t) => {
      setToken(t);
      set(t);
    },
    signOut: () => {
      setToken(null);
      set(null);
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
