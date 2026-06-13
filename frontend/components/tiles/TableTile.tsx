"use client";

interface Config {
  columns?: string[];
  rows?: (string | number)[][];
  max_rows?: number;
}

export default function TableTile({ config }: { config: Config }) {
  const { columns = [], rows = [], max_rows = 8 } = config;
  const visible = rows.slice(0, max_rows);
  const overflow = rows.length - max_rows;

  return (
    <div style={{ height: "100%", overflowX: "auto", overflowY: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        {columns.length > 0 && (
          <thead>
            <tr>
              {columns.map((col, i) => (
                <th
                  key={i}
                  style={{
                    textAlign: "left",
                    padding: "4px 8px",
                    fontSize: 11,
                    fontWeight: 600,
                    color: "var(--fm)",
                    borderBottom: "1px solid var(--bd)",
                    whiteSpace: "nowrap",
                    position: "sticky",
                    top: 0,
                    background: "var(--surface)",
                  }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {visible.map((row, ri) => (
            <tr key={ri} style={{ background: ri % 2 === 1 ? "var(--s2)" : "transparent" }}>
              {(Array.isArray(row) ? row : [row]).map((cell, ci) => (
                <td
                  key={ci}
                  style={{
                    padding: "4px 8px",
                    color: "var(--fd)",
                    borderBottom: "1px solid var(--bd)",
                    whiteSpace: "nowrap",
                    maxWidth: 200,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {String(cell ?? "")}
                </td>
              ))}
            </tr>
          ))}
          {overflow > 0 && (
            <tr>
              <td
                colSpan={columns.length || 1}
                style={{ padding: "4px 8px", fontSize: 11, color: "var(--fm)", fontStyle: "italic" }}
              >
                + {overflow} more rows
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
