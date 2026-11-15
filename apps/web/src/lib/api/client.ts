import createClient from "openapi-fetch";
import type { paths } from "./schema";

export function apiClient() {
  return createClient<paths>({ baseUrl: process.env.API_INTERNAL_URL ?? "http://localhost:8000" });
}
