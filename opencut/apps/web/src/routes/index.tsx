import { createFileRoute } from "@tanstack/react-router";
import { V2VApp } from "../extensions/v2v";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
  return <V2VApp />;
}
