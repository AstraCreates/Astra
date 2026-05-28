"use client";

import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type AnyData = Record<string, unknown>;

function useAdminFetch<T = AnyData>(path: string, interval = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${API}/admin/${path}`);
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
      setLastUpdated(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    fetch_();
    const t = setInterval(fetch_, interval);
    return () => clearInterval(t);
  }, [fetch_, interval]);

  return { data, error, loading, lastUpdated, refetch: fetch_ };
}

// ── Primitives ────────────────────────────────

function Card({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`admin-card ${className}`}>
      <div className="admin-card-title">{title}</div>
      {children}
    </div>
  );
}

function Stat({ label, value, unit = "", color }: { label: string; value: unknown; unit?: string; color?: string }) {
  const formatted = value === null || value === undefined ? "—" : String(value);
  return (
    <div className="admin-stat">
      <span className="admin-stat-label">{label}</span>
      <span className="admin-stat-value" style={color ? { color } : undefined}>
        {formatted}{unit && <span className="admin-stat-unit"> {unit}</span>}
      </span>
    </div>
  );
}

function Bar({ pct, color = "#3b82f6" }: { pct: number; color?: string }) {
  const clamped = Math.min(100, Math.max(0, pct));
  const c = clamped > 85 ? "#ef4444" : clamped > 65 ? "#f59e0b" : color;
  return (
    <div className="admin-bar-track">
      <div className="admin-bar-fill" style={{ width: `${clamped}%`, background: c }} />
      <span className="admin-bar-label">{clamped.toFixed(1)}%</span>
    </div>
  );
}

function Badge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: "#3b82f6", completed: "#22c55e", done: "#22c55e",
    error: "#ef4444", waiting: "#94a3b8",
  };
  return (
    <span className="admin-badge" style={{ background: colors[status] || "#64748b" }}>
      {status}
    </span>
  );
}

function Ago({ date }: { date: Date | null }) {
  if (!date) return null;
  const secs = Math.floor((Date.now() - date.getTime()) / 1000);
  return <span className="admin-ago">{secs < 60 ? `${secs}s ago` : `${Math.floor(secs / 60)}m ago`}</span>;
}

function Table({ headers, rows }: { headers: string[]; rows: (string | number | React.ReactNode)[][] }) {
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead>
          <tr>{headers.map(h => <th key={h}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return <h2 className="admin-section-header">{children}</h2>;
}

// ── Panels ────────────────────────────────────

function OverviewPanel() {
  const { data, error, lastUpdated } = useAdminFetch("overview", 4000);
  const d = data as AnyData;
  if (error) return <Card title="Overview"><p className="admin-error">{error}</p></Card>;
  if (!d) return <Card title="Overview"><p className="admin-loading">Loading…</p></Card>;

  const sys = d.system as AnyData;
  const sess = d.sessions as AnyData;
  const agents = d.agents as AnyData;

  return (
    <Card title="Overview">
      <div className="admin-overview-grid">
        <div className="admin-overview-block">
          <div className="admin-overview-block-label">CPU</div>
          <Bar pct={Number(sys.cpu_percent)} />
        </div>
        <div className="admin-overview-block">
          <div className="admin-overview-block-label">Memory {sys.mem_used_gb}GB / {sys.mem_total_gb}GB</div>
          <Bar pct={Number(sys.mem_percent)} color="#a78bfa" />
        </div>
        <div className="admin-overview-block">
          <div className="admin-overview-block-label">Disk</div>
          <Bar pct={Number(sys.disk_percent)} color="#f59e0b" />
        </div>
        <div className="admin-overview-block">
          <div className="admin-overview-block-label">Load avg (1/5/15m)</div>
          <span className="admin-mono">
            {(sys.load_avg as number[]).join(" / ")}
          </span>
        </div>
      </div>

      <div className="admin-stat-row">
        <Stat label="Process RSS" value={sys.process_rss_mb} unit="MB" />
        <Stat label="Sessions active" value={String(sess.active)} color="#3b82f6" />
        <Stat label="Sessions done" value={String(sess.completed)} color="#22c55e" />
        <Stat label="Agent runs" value={String(agents.total_runs)} />
        <Stat label="Agent errors" value={String(agents.total_errors)} color={Number(agents.total_errors) > 0 ? "#ef4444" : undefined} />
        <Stat label="Error rate" value={String(agents.error_rate_pct)} unit="%" color={Number(agents.error_rate_pct) > 10 ? "#ef4444" : "#22c55e"} />
        <Stat label="Unique founders" value={String((d.founders as AnyData).unique)} />
        <Stat label="Events in memory" value={String((d.events as AnyData).total)} />
      </div>

      <div style={{ marginTop: 12 }}>
        <div className="admin-card-subtitle">Top agents by runs</div>
        <Table
          headers={["Agent", "Runs"]}
          rows={(agents.top_5 as AnyData[]).map(a => [String(a.agent), String(a.runs)])}
        />
      </div>
      <Ago date={lastUpdated} />
    </Card>
  );
}

function SystemPanel() {
  const { data, error, lastUpdated } = useAdminFetch("system", 5000);
  const d = data as AnyData;
  if (error) return <Card title="System"><p className="admin-error">{error}</p></Card>;
  if (!d) return <Card title="System"><p className="admin-loading">Loading…</p></Card>;

  const cpu = d.cpu as AnyData;
  const mem = d.memory as AnyData;
  const disk = d.disk as AnyData;
  const net = d.network as AnyData;
  const proc = d.process as AnyData;

  return (
    <Card title={`System — ${d.host} · ${d.os} · Python ${d.python}`}>
      <div className="admin-grid-2">
        <div>
          <div className="admin-card-subtitle">CPU</div>
          <div className="admin-stat-row">
            <Stat label="Total" value={Number(cpu.percent_total).toFixed(1)} unit="%" />
            <Stat label="Cores (logical)" value={String(cpu.count_logical)} />
            <Stat label="Cores (physical)" value={String(cpu.count_physical)} />
            <Stat label="Freq" value={String(cpu.freq_current_mhz)} unit="MHz" />
            <Stat label="Load 1m" value={String(cpu.load_avg_1m)} />
            <Stat label="Load 5m" value={String(cpu.load_avg_5m)} />
            <Stat label="Load 15m" value={String(cpu.load_avg_15m)} />
          </div>
          <div className="admin-card-subtitle" style={{ marginTop: 8 }}>CPU times (s)</div>
          <div className="admin-stat-row">
            {Object.entries(cpu.times as Record<string, number>).map(([k, v]) => (
              <Stat key={k} label={k} value={v} />
            ))}
          </div>
          <div className="admin-card-subtitle" style={{ marginTop: 8 }}>Per-core %</div>
          <div className="admin-cores">
            {(cpu.percent_per_core as number[]).map((pct, i) => (
              <div key={i} className="admin-core">
                <div className="admin-core-label">C{i}</div>
                <Bar pct={pct} />
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="admin-card-subtitle">Memory</div>
          <Bar pct={Number(mem.percent)} color="#a78bfa" />
          <div className="admin-stat-row" style={{ marginTop: 4 }}>
            <Stat label="Used" value={String(mem.used_gb)} unit="GB" />
            <Stat label="Available" value={String(mem.available_gb)} unit="GB" />
            <Stat label="Total" value={String(mem.total_gb)} unit="GB" />
            <Stat label="Cached" value={String(mem.cached_gb)} unit="GB" />
            <Stat label="Buffers" value={String(mem.buffers_gb)} unit="GB" />
            <Stat label="Swap used" value={String(mem.swap_used_gb)} unit="GB" />
            <Stat label="Swap %" value={String(mem.swap_percent)} unit="%" />
          </div>

          <div className="admin-card-subtitle" style={{ marginTop: 10 }}>Disk</div>
          <Bar pct={Number(disk.percent)} color="#f59e0b" />
          <div className="admin-stat-row" style={{ marginTop: 4 }}>
            <Stat label="Used" value={String(disk.used_gb)} unit="GB" />
            <Stat label="Free" value={String(disk.free_gb)} unit="GB" />
            <Stat label="Total" value={String(disk.total_gb)} unit="GB" />
            <Stat label="IO reads" value={String(disk.io_read_mb)} unit="MB" />
            <Stat label="IO writes" value={String(disk.io_write_mb)} unit="MB" />
          </div>

          <div className="admin-card-subtitle" style={{ marginTop: 10 }}>Network (cumulative)</div>
          <div className="admin-stat-row">
            <Stat label="Sent" value={String(net.bytes_sent_mb)} unit="MB" />
            <Stat label="Recv" value={String(net.bytes_recv_mb)} unit="MB" />
            <Stat label="Pkts sent" value={String(net.packets_sent)} />
            <Stat label="Pkts recv" value={String(net.packets_recv)} />
            <Stat label="Err in" value={String(net.errin)} />
            <Stat label="Err out" value={String(net.errout)} />
            <Stat label="Drop in" value={String(net.dropin)} />
          </div>

          <div className="admin-card-subtitle" style={{ marginTop: 10 }}>This process</div>
          <div className="admin-stat-row">
            <Stat label="PID" value={String(proc.pid)} />
            <Stat label="RSS" value={String(proc.rss_mb)} unit="MB" />
            <Stat label="VMS" value={String(proc.vms_mb)} unit="MB" />
            <Stat label="CPU%" value={String(proc.cpu_percent)} unit="%" />
            <Stat label="Threads" value={String(proc.threads)} />
            <Stat label="FDs" value={String(proc.open_fds)} />
            <Stat label="Conns" value={String(proc.open_connections)} />
            <Stat label="Children" value={String(proc.child_processes)} />
          </div>
        </div>
      </div>
      <Ago date={lastUpdated} />
    </Card>
  );
}

function ProcessesPanel() {
  const [sort, setSort] = useState<"cpu" | "mem">("cpu");
  const { data, error, lastUpdated } = useAdminFetch(`system/processes?sort_by=${sort}`, 8000);
  const d = data as AnyData;

  return (
    <Card title="Top Processes">
      <div style={{ marginBottom: 8 }}>
        <button className={`admin-tab-btn ${sort === "cpu" ? "active" : ""}`} onClick={() => setSort("cpu")}>CPU</button>
        <button className={`admin-tab-btn ${sort === "mem" ? "active" : ""}`} onClick={() => setSort("mem")}>Memory</button>
        <Ago date={lastUpdated} />
      </div>
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <Table
          headers={["PID", "Name", "CPU%", "RSS MB", "Status", "Age", "Cmd"]}
          rows={(d.processes as AnyData[]).map(p => [
            String(p.pid),
            String(p.name),
            `${Number(p.cpu_percent).toFixed(1)}%`,
            String(p.rss_mb),
            String(p.status),
            p.age_s !== null ? `${Math.floor(Number(p.age_s) / 60)}m` : "—",
            <span key="cmd" className="admin-mono admin-truncate" title={String(p.cmd)}>{String(p.cmd).slice(0, 60)}</span>,
          ])}
        />
      )}
    </Card>
  );
}

function SessionsPanel() {
  const { data, error, lastUpdated, refetch } = useAdminFetch("sessions", 5000);
  const d = data as AnyData;

  return (
    <Card title="Sessions">
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <>
          <div className="admin-stat-row" style={{ marginBottom: 10 }}>
            <Stat label="Total" value={String(d.total)} />
            <Stat label="Active" value={String(d.active)} color="#3b82f6" />
            <Stat label="Completed" value={String(d.completed)} color="#22c55e" />
            <button className="admin-refresh-btn" onClick={refetch}>↻</button>
            <Ago date={lastUpdated} />
          </div>
          <Table
            headers={["Session", "Status", "Founder", "Goal", "Agents", "Events", "Errors", "Queue", "Steer"]}
            rows={(d.sessions as AnyData[]).map(s => [
              <span key="sid" className="admin-mono admin-dim">{String(s.session_id)}</span>,
              <Badge key="st" status={String(s.status)} />,
              <span key="fid" className="admin-mono admin-dim">{String(s.founder_id || "—").slice(0, 12)}</span>,
              <span key="goal" title={String(s.goal || "")}>{String(s.goal || "—").slice(0, 50)}</span>,
              String(s.agent_count),
              String(s.event_count),
              <span key="errs" style={{ color: Number(s.error_count) > 0 ? "#ef4444" : undefined }}>{String(s.error_count)}</span>,
              String(s.queue_depth),
              String(s.steer_messages),
            ])}
          />
        </>
      )}
    </Card>
  );
}

function AgentsPanel() {
  const { data, error, lastUpdated } = useAdminFetch("agents", 6000);
  const d = data as AnyData;

  return (
    <Card title="Agent Activity">
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <>
          <div style={{ marginBottom: 8 }}><Ago date={lastUpdated} /></div>
          <Table
            headers={["Agent", "Runs", "Done", "Errors", "Success%", "Avg dur", "Sessions", "Last status"]}
            rows={(d.agents as AnyData[]).map(a => [
              <span key="n" className="admin-agent-name">{String(a.agent)}</span>,
              String(a.runs),
              String(a.completions),
              <span key="e" style={{ color: Number(a.errors) > 0 ? "#ef4444" : undefined }}>{String(a.errors)}</span>,
              a.success_rate_pct !== null ? `${a.success_rate_pct}%` : "—",
              a.avg_duration_s !== null ? `${a.avg_duration_s}s` : "—",
              String(a.session_count),
              <Badge key="ls" status={String(a.last_status || "—")} />,
            ])}
          />
        </>
      )}
    </Card>
  );
}

function ErrorsPanel() {
  const { data, error, lastUpdated } = useAdminFetch("errors", 8000);
  const d = data as AnyData;

  return (
    <Card title="All Errors">
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <>
          <div className="admin-stat-row" style={{ marginBottom: 10 }}>
            <Stat label="Total errors" value={String(d.total_errors)} color={Number(d.total_errors) > 0 ? "#ef4444" : "#22c55e"} />
            <Ago date={lastUpdated} />
          </div>
          {(d.errors as AnyData[]).length === 0 ? (
            <p className="admin-ok">No errors ✓</p>
          ) : (
            <Table
              headers={["Session", "Agent", "Error"]}
              rows={(d.errors as AnyData[]).map(e => [
                <span key="s" className="admin-mono admin-dim">{String(e.session_id)}</span>,
                <span key="a" className="admin-agent-name">{String(e.agent)}</span>,
                <span key="e" className="admin-error-msg" title={String(e.error)}>{String(e.error).slice(0, 120)}</span>,
              ])}
            />
          )}
        </>
      )}
    </Card>
  );
}

function FoundersPanel() {
  const { data, error, lastUpdated } = useAdminFetch("founders", 10000);
  const d = data as AnyData;

  return (
    <Card title="Founders">
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <>
          <div className="admin-stat-row" style={{ marginBottom: 10 }}>
            <Stat label="Unique founders" value={String(d.unique_founders)} />
            <Ago date={lastUpdated} />
          </div>
          <Table
            headers={["Founder ID", "Sessions", "Active", "Completed", "Agent runs", "Errors"]}
            rows={(d.founders as AnyData[]).map(f => [
              <span key="id" className="admin-mono admin-dim">{String(f.founder_id).slice(0, 20)}</span>,
              String((f.sessions as unknown[]).length),
              String(f.active_sessions),
              String(f.completed_sessions),
              String(f.total_agent_runs),
              <span key="e" style={{ color: Number(f.total_errors) > 0 ? "#ef4444" : undefined }}>{String(f.total_errors)}</span>,
            ])}
          />
        </>
      )}
    </Card>
  );
}

function RedisPanel() {
  const { data, error, lastUpdated } = useAdminFetch("redis", 8000);
  const d = data as AnyData;

  return (
    <Card title="Redis">
      {error && <p className="admin-error">{error}</p>}
      {d && !d.connected && <p className="admin-error">Not connected: {String(d.error)}</p>}
      {d && d.connected && (() => {
        const mem = d.memory as AnyData;
        const stats = d.stats as AnyData;
        const clients = d.clients as AnyData;
        return (
          <>
            <div className="admin-stat-row">
              <Stat label="Version" value={String(d.version)} />
              <Stat label="Role" value={String(d.role)} />
              <Stat label="Uptime" value={String(d.uptime_human)} />
              <Stat label="Total keys" value={String(d.total_keys)} />
            </div>
            <div className="admin-grid-2" style={{ marginTop: 10 }}>
              <div>
                <div className="admin-card-subtitle">Clients</div>
                <div className="admin-stat-row">
                  <Stat label="Connected" value={String(clients.connected)} />
                  <Stat label="Blocked" value={String(clients.blocked)} />
                  <Stat label="Max" value={String(clients.max)} />
                </div>
                <div className="admin-card-subtitle" style={{ marginTop: 8 }}>Memory</div>
                <div className="admin-stat-row">
                  <Stat label="Used" value={String(mem.used_mb)} unit="MB" />
                  <Stat label="Peak" value={String(mem.used_peak_mb)} unit="MB" />
                  <Stat label="RSS" value={String(mem.used_rss_mb)} unit="MB" />
                  <Stat label="Frag ratio" value={String(mem.fragmentation_ratio)} />
                </div>
              </div>
              <div>
                <div className="admin-card-subtitle">Stats</div>
                <div className="admin-stat-row">
                  <Stat label="Cmds processed" value={String(stats.total_commands_processed)} />
                  <Stat label="Connections rcvd" value={String(stats.total_connections_received)} />
                  <Stat label="Keyspace hits" value={String(stats.keyspace_hits)} />
                  <Stat label="Keyspace misses" value={String(stats.keyspace_misses)} />
                  <Stat label="Hit rate" value={String(stats.hit_rate_pct)} unit="%" color={Number(stats.hit_rate_pct) > 80 ? "#22c55e" : "#f59e0b"} />
                  <Stat label="Expired keys" value={String(stats.expired_keys)} />
                  <Stat label="Evicted keys" value={String(stats.evicted_keys)} color={Number(stats.evicted_keys) > 0 ? "#ef4444" : undefined} />
                  <Stat label="Ops/sec" value={String(stats.ops_per_sec)} />
                  <Stat label="In kbps" value={String(stats.input_kbps)} />
                  <Stat label="Out kbps" value={String(stats.output_kbps)} />
                </div>
              </div>
            </div>
            <Ago date={lastUpdated} />
          </>
        );
      })()}
    </Card>
  );
}

function GitPanel() {
  const { data, error, lastUpdated, refetch } = useAdminFetch("git", 15000);
  const d = data as AnyData;

  return (
    <Card title="Git / Deployment">
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <>
          <div className="admin-stat-row" style={{ marginBottom: 8 }}>
            <Stat label="Branch" value={String(d.branch)} />
            <Stat label="Commit" value={String(d.commit_short)} />
            <Stat label="Behind origin" value={String(d.commits_behind_origin ?? "—")} color={Number(d.commits_behind_origin) > 0 ? "#f59e0b" : "#22c55e"} />
            <Stat label="In sync" value={d.in_sync ? "✓" : "✗"} color={d.in_sync ? "#22c55e" : "#ef4444"} />
            <Stat label="Dirty" value={d.dirty ? "yes" : "no"} color={d.dirty ? "#f59e0b" : "#22c55e"} />
            <button className="admin-refresh-btn" onClick={refetch}>↻</button>
            <Ago date={lastUpdated} />
          </div>
          <div className="admin-card-subtitle">Last commit</div>
          <p className="admin-mono admin-dim" style={{ marginBottom: 8 }}>{String(d.commit_message)} — {String(d.commit_date)}</p>
          <div className="admin-card-subtitle">Recent commits</div>
          <div className="admin-log-block">
            {(d.recent_commits as string[]).map((c, i) => (
              <div key={i} className="admin-log-line">{c}</div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

function EnvPanel() {
  const { data, error } = useAdminFetch("env", 30000);
  const d = data as Record<string, string> | null;

  return (
    <Card title="Environment">
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <Table
          headers={["Key", "Status"]}
          rows={Object.entries(d).map(([k, v]) => [
            <span key="k" className="admin-mono">{k}</span>,
            <span key="v" style={{ color: v === "NOT SET" ? "#ef4444" : "#22c55e" }} className="admin-mono">{v}</span>,
          ])}
        />
      )}
    </Card>
  );
}

function AsyncioPanel() {
  const { data, error, lastUpdated } = useAdminFetch("asyncio", 6000);
  const d = data as AnyData;

  return (
    <Card title="Asyncio Tasks">
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <>
          <div className="admin-stat-row" style={{ marginBottom: 8 }}>
            <Stat label="Total tasks" value={String(d.total_tasks)} />
            <Stat label="Running" value={String(d.running)} color="#3b82f6" />
            <Ago date={lastUpdated} />
          </div>
          <div className="admin-card-subtitle">Top coroutines</div>
          <Table
            headers={["Coroutine", "Count"]}
            rows={Object.entries(d.top_coros as Record<string, number>).map(([k, v]) => [
              <span key="k" className="admin-mono admin-dim">{k}</span>,
              String(v),
            ])}
          />
        </>
      )}
    </Card>
  );
}

function LogsPanel() {
  const [filter, setFilter] = useState("");
  const [filterInput, setFilterInput] = useState("");
  const { data, error, lastUpdated, refetch } = useAdminFetch(
    `logs?lines=300${filter ? `&filter=${encodeURIComponent(filter)}` : ""}`,
    0
  );
  const d = data as AnyData;

  return (
    <Card title="Logs">
      <div style={{ display: "flex", gap: 8, marginBottom: 10, alignItems: "center" }}>
        <input
          className="admin-input"
          placeholder="Filter logs…"
          value={filterInput}
          onChange={e => setFilterInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && setFilter(filterInput)}
        />
        <button className="admin-tab-btn active" onClick={() => setFilter(filterInput)}>Filter</button>
        <button className="admin-tab-btn" onClick={() => { setFilter(""); setFilterInput(""); }}>Clear</button>
        <button className="admin-refresh-btn" onClick={refetch}>↻ Refresh</button>
        <Ago date={lastUpdated} />
      </div>
      {error && <p className="admin-error">{error}</p>}
      {d && (
        <div className="admin-log-block admin-log-block-tall">
          {(d.lines as string[]).map((line, i) => {
            const isError = /error|exception|traceback|failed/i.test(line);
            const isWarn = /warn|warning/i.test(line);
            return (
              <div key={i} className="admin-log-line" style={{
                color: isError ? "#f87171" : isWarn ? "#fbbf24" : undefined,
              }}>{line}</div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

// ── Main page ─────────────────────────────────

const TABS = ["Overview", "System", "Processes", "Sessions", "Agents", "Errors", "Founders", "Redis", "Git", "Env", "Asyncio", "Logs"] as const;
type Tab = typeof TABS[number];

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("Overview");

  return (
    <div className="admin-root">
      <style>{`
        .admin-root {
          min-height: 100vh;
          background: #0a0d12;
          color: #c8d0da;
          font-family: var(--font-jetbrains-mono, monospace);
          font-size: 12px;
        }
        .admin-header {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 16px 20px 0;
          border-bottom: 1px solid rgba(255,255,255,0.06);
          flex-wrap: wrap;
        }
        .admin-title {
          font-size: 14px;
          font-weight: 700;
          color: #e2e8f0;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin-right: 8px;
        }
        .admin-tabs {
          display: flex;
          gap: 2px;
          flex-wrap: wrap;
        }
        .admin-tab {
          padding: 7px 14px;
          border: none;
          background: transparent;
          color: #64748b;
          font-family: inherit;
          font-size: 11px;
          cursor: pointer;
          border-bottom: 2px solid transparent;
          transition: color 0.15s, border-color 0.15s;
          letter-spacing: 0.04em;
        }
        .admin-tab:hover { color: #94a3b8; }
        .admin-tab.active { color: #e2e8f0; border-bottom-color: #3b82f6; }
        .admin-body { padding: 16px 20px 40px; }
        .admin-card {
          background: rgba(255,255,255,0.035);
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 8px;
          padding: 16px;
          margin-bottom: 16px;
        }
        .admin-card-title {
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.1em;
          color: #94a3b8;
          margin-bottom: 14px;
          padding-bottom: 8px;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .admin-card-subtitle {
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: #475569;
          margin-bottom: 6px;
        }
        .admin-stat-row { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; }
        .admin-stat { display: flex; flex-direction: column; gap: 2px; }
        .admin-stat-label { font-size: 10px; color: #475569; text-transform: uppercase; letter-spacing: 0.06em; }
        .admin-stat-value { font-size: 15px; font-weight: 700; color: #e2e8f0; }
        .admin-stat-unit { font-size: 10px; color: #64748b; font-weight: 400; }
        .admin-bar-track {
          height: 8px; background: rgba(255,255,255,0.08); border-radius: 4px;
          position: relative; overflow: hidden; min-width: 120px; margin: 4px 0;
        }
        .admin-bar-fill { height: 100%; border-radius: 4px; transition: width 0.4s; }
        .admin-bar-label {
          position: absolute; right: 4px; top: 50%; transform: translateY(-50%);
          font-size: 9px; color: rgba(255,255,255,0.7); font-weight: 600;
        }
        .admin-overview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
        .admin-overview-block { }
        .admin-overview-block-label { font-size: 10px; color: #475569; margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.06em; }
        .admin-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
        @media (max-width: 900px) { .admin-grid-2 { grid-template-columns: 1fr; } }
        .admin-cores { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 6px; margin-top: 4px; }
        .admin-core { }
        .admin-core-label { font-size: 9px; color: #475569; margin-bottom: 2px; }
        .admin-table-wrap { overflow-x: auto; }
        .admin-table { width: 100%; border-collapse: collapse; font-size: 11px; }
        .admin-table th { text-align: left; padding: 5px 8px; font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; color: #475569; border-bottom: 1px solid rgba(255,255,255,0.06); white-space: nowrap; }
        .admin-table td { padding: 5px 8px; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: top; }
        .admin-table tr:hover td { background: rgba(255,255,255,0.02); }
        .admin-badge { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 10px; font-weight: 600; color: #fff; }
        .admin-mono { font-family: inherit; }
        .admin-dim { color: #475569; }
        .admin-truncate { display: inline-block; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }
        .admin-agent-name { color: #93c5fd; font-weight: 600; }
        .admin-log-block {
          background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.05);
          border-radius: 4px; padding: 10px; max-height: 320px; overflow-y: auto; font-size: 11px; line-height: 1.6;
        }
        .admin-log-block-tall { max-height: 600px; }
        .admin-log-line { white-space: pre-wrap; word-break: break-all; color: #94a3b8; }
        .admin-error { color: #f87171; font-size: 11px; }
        .admin-error-msg { color: #fca5a5; font-size: 10px; }
        .admin-ok { color: #4ade80; }
        .admin-loading { color: #475569; }
        .admin-ago { font-size: 10px; color: #334155; }
        .admin-refresh-btn { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; color: #94a3b8; font-family: inherit; font-size: 11px; padding: 3px 8px; cursor: pointer; }
        .admin-refresh-btn:hover { background: rgba(255,255,255,0.1); }
        .admin-tab-btn { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; color: #64748b; font-family: inherit; font-size: 11px; padding: 3px 10px; cursor: pointer; }
        .admin-tab-btn.active, .admin-tab-btn:hover { background: rgba(59,130,246,0.15); color: #93c5fd; border-color: rgba(59,130,246,0.3); }
        .admin-input { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; color: #c8d0da; font-family: inherit; font-size: 11px; padding: 4px 10px; outline: none; min-width: 200px; }
        .admin-input:focus { border-color: rgba(59,130,246,0.4); }
        .admin-section-header { font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: #334155; margin: 20px 0 8px; }
      `}</style>

      <div className="admin-header">
        <span className="admin-title">⬡ Astra Admin</span>
        <div className="admin-tabs">
          {TABS.map(t => (
            <button key={t} className={`admin-tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="admin-body">
        {tab === "Overview"   && <OverviewPanel />}
        {tab === "System"     && <SystemPanel />}
        {tab === "Processes"  && <ProcessesPanel />}
        {tab === "Sessions"   && <SessionsPanel />}
        {tab === "Agents"     && <AgentsPanel />}
        {tab === "Errors"     && <ErrorsPanel />}
        {tab === "Founders"   && <FoundersPanel />}
        {tab === "Redis"      && <RedisPanel />}
        {tab === "Git"        && <GitPanel />}
        {tab === "Env"        && <EnvPanel />}
        {tab === "Asyncio"    && <AsyncioPanel />}
        {tab === "Logs"       && <LogsPanel />}
      </div>
    </div>
  );
}
