export interface Persona {
  email: string;
  display_name: string;
  title: string;
  groups: string[];
}

export interface AnswerModel {
  id: string;
  label: string;
  default?: boolean;
}

export interface AppConfig {
  dataStoreId: string;
  identitySource: string;
  personas: Persona[];
  facetFields: string[];
  models: AnswerModel[];
}

// per-request AI options chosen in the UI
export interface AiOpts {
  model?: string;
  useSearch?: boolean;
  searchId?: string; // correlates the AI turn back to the originating search
}

export interface SearchResult {
  documentId: string;
  title: string;
  sourceUrl?: string;
  gcsUri?: string;
  snippet?: string;
  company?: string;
  department?: string;
  doc_type?: string;
  report_kind?: string;
  research_source?: string;
  research_area?: string;
  venue?: string;
  year?: string;
  publish_date?: string;
  rerankScore?: number; // semantic Ranking API relevance (0-1); shown in demo mode
}

export interface Citation {
  index: number;
  title: string;
  sourceUrl?: string;
  snippet?: string;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface SearchResponse {
  user: string;
  searchId?: string;
  results: SearchResult[];
  citations: Citation[];
  appliedFilters: Record<string, string | string[]>;
  availableFilters: Record<string, FacetValue[]>;
}

// AI answer is served separately (opt-in) by /api/answer so search stays fast.
export interface AnswerResponse {
  user: string;
  summary: string;
  citations: Citation[];
}
