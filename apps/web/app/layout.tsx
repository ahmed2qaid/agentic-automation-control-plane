import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'FlowGuard — Agentic Automation Control Plane',
  description: 'Policy, approval, and observability control plane for n8n workflows and AI agents.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
