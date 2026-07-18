import CompanyHome from "@/components/CompanyHome";

// Company Home is live operational state; never serve an old dashboard shell
// after a deploy while its client bundle and API contract have changed.
export const dynamic = "force-dynamic";

export default function DashboardPage() {
  return <CompanyHome />;
}
