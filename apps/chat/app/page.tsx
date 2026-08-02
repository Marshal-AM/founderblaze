import { AgentApp } from "../components/AgentApp";

// Must be dynamic: AUTH_GOOGLE_* is only available at runtime on Railway,
// not during the Docker image build (where googleEnabled would bake as false).
export const dynamic = "force-dynamic";

export default function Page() {
  const googleEnabled = Boolean(
    process.env.AUTH_GOOGLE_ID || process.env.GOOGLE_CLIENT_ID
  );
  return <AgentApp googleEnabled={googleEnabled} />;
}
