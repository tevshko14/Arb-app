/** API response types matching the FastAPI backend Pydantic models. */

export interface EventResponse {
  id: string;
  sport: string;
  league: string;
  home_team: string;
  away_team: string;
  commence_time: string | null;
  status: string;
}

export interface OddsResponse {
  bookmaker: string;
  bookmaker_name: string;
  is_sharp: boolean;
  market: string;
  outcome: string;
  price: number;
  point: number | null;
  updated_at: string | null;
}

export interface SignalResponse {
  event_id: string;
  sport: string;
  home_team: string;
  away_team: string;
  bookmaker: string;
  outcome: string;
  decimal_odds: number;
  model_prob: number;
  sharp_prob: number;
  edge_pct: number;
  kelly_fraction_pct: number;
  recommended_stake: number;
  confidence: number;
}

export interface CalibrationResponse {
  n_predictions: number;
  n_resolved: number;
  brier_ensemble: number | null;
  brier_sharp: number | null;
  brier_model: number | null;
  edge_over_sharp: number | null;
  calibration_bins: CalibrationBin[];
}

export interface CalibrationBin {
  bin_range: string;
  n_predictions: number;
  mean_predicted: number;
  mean_actual: number;
  calibration_error: number;
}

export interface RiskStateResponse {
  risk_level: string;
  kelly_multiplier: number;
  max_stake_fraction: number;
  max_portfolio_exposure: number;
  current_bankroll: number;
  peak_bankroll: number;
  drawdown_pct: number;
  active_exposure: number;
  active_exposure_pct: number;
  recent_win_rate: number | null;
  total_bets: number;
  total_pnl: number;
}

export interface CLVReportResponse {
  total_signals: number;
  signals_with_closing: number;
  mean_clv: number | null;
  median_clv: number | null;
  positive_clv_pct: number | null;
  market_efficiency_score: number | null;
  bookmaker_softness: BookmakerSoftness[];
}

export interface BookmakerSoftness {
  bookmaker: string;
  total_signals: number;
  softness_score: number;
  mean_clv: number | null;
  mean_edge: number;
}

export interface LineAlertResponse {
  event_id: string;
  movement_type: string;
  priority: string;
  bookmaker: string;
  outcome: string;
  old_odds: number;
  new_odds: number;
  odds_change_pct: number;
  description: string;
}

export interface HealthResponse {
  status: string;
  database: Record<string, unknown>;
  redis: Record<string, unknown>;
  scheduler_tier: string;
}

export interface QuotaResponse {
  requests_remaining: number | null;
  warning: boolean;
  message: string | null;
}
