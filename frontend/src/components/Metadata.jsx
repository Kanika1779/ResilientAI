export default function Metadata({ meta }) {
  const cached = meta.resolution_source === "LLM_CACHE";
  return (
    <div className="meta">
      <span className={`pill ${cached ? "pill-cache" : "pill-live"}`} data-testid="meta-source">
        {meta.resolution_source}
      </span>
      <span className="meta-item" title="Model">
        <span className="meta-label">model</span>
        <span data-testid="meta-model">{meta.model}</span>
      </span>
      <span className="meta-item" title="Server-measured latency">
        <span className="meta-label">latency</span>
        <span data-testid="meta-latency">{meta.latency_ms} ms</span>
      </span>
      <span className="meta-item" title="Input tokens for this request">
        <span className="meta-label">in</span>
        <span data-testid="meta-input-tokens">{meta.input_tokens}</span>
      </span>
      <span className="meta-item" title="Output tokens for this reply">
        <span className="meta-label">out</span>
        <span data-testid="meta-output-tokens">{meta.output_tokens}</span>
      </span>
      {meta.key_id && (
        <span className="meta-item" title="API key that served this request">
          <span className="meta-label">key</span>
          <span>
            {meta.key_id}
            {meta.fallback_attempts > 0 && ` · ${meta.fallback_attempts} failover`}
          </span>
        </span>
      )}
    </div>
  );
}
