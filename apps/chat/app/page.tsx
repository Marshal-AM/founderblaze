import { AgentApp } from "../components/AgentApp";

export default function Page() {
  const googleEnabled = Boolean(
    process.env.AUTH_GOOGLE_ID || process.env.GOOGLE_CLIENT_ID
  );
  return <AgentApp googleEnabled={googleEnabled} />;
}
