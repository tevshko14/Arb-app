/**
 * API client for the Bet Buddy FastAPI backend.
 * All functions return typed responses matching backend Pydantic models.
 */

import type {
  EventResponse,
  OddsResponse,
  SignalResponse,
  CalibrationResponse,
  RiskStateResponse,
  CLVReportResponse,
  LineAlertResponse,
  HealthResponse,
  QuotaResponse,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchJSON<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API_BASE);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") url.searchParams.set(k, v);
    });
  }

  const res = await fetch(url.toString(), {
    next: { revalidate: 30 },
  });

  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }

  return res.json() as Promise<T>;
}

// ──────── Health ────────

export function getHealth(): Promise<HealthResponse> {
  return fetchJSON<HealthResponse>("/health");
}

export function getQuota(): Promise<QuotaResponse> {
  return fetchJSON<QuotaResponse>("/quota");
}

// ──────── Events ────────

export function getEvents(params?: {
  sport?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<EventResponse[]> {
  const p: Record<string, string> = {};
  if (params?.sport) p.sport = params.sport;
  if (params?.status) p.status = params.status;
  if (params?.limit) p.limit = String(params.limit);
  if (params?.offset) p.offset = String(params.offset);
  return fetchJSON<EventResponse[]>("/events", p);
}

export function getOdds(eventId: string): Promise<OddsResponse[]> {
  return fetchJSON<OddsResponse[]>(`/odds/${eventId}`);
}

// ──────── Signals ────────

export function getSignals(params?: {
  sport?: string;
  min_edge?: number;
  limit?: number;
}): Promise<SignalResponse[]> {
  const p: Record<string, string> = {};
  if (params?.sport) p.sport = params.sport;
  if (params?.min_edge !== undefined) p.min_edge = String(params.min_edge);
  if (params?.limit) p.limit = String(params.limit);
  return fetchJSON<SignalResponse[]>("/signals", p);
}

// ──────── Calibration ────────

export function getCalibration(): Promise<CalibrationResponse> {
  return fetchJSON<CalibrationResponse>("/calibration");
}

// ──────── Risk ────────

export function getRiskState(): Promise<RiskStateResponse> {
  return fetchJSON<RiskStateResponse>("/risk");
}

// ──────── CLV ────────

export function getCLVReport(): Promise<CLVReportResponse> {
  return fetchJSON<CLVReportResponse>("/clv");
}

// ──────── Alerts ────────

export function getAlerts(params?: {
  hours?: number;
  priority?: string;
}): Promise<LineAlertResponse[]> {
  const p: Record<string, string> = {};
  if (params?.hours) p.hours = String(params.hours);
  if (params?.priority) p.priority = params.priority;
  return fetchJSON<LineAlertResponse[]>("/alerts", p);
}
