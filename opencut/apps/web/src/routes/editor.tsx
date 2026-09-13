import { createFileRoute } from '@tanstack/react-router';
import { V2VApp } from '../extensions/v2v';

export const Route = createFileRoute('/editor')({ component: Editor });

function Editor() {
  return <V2VApp />;
}
