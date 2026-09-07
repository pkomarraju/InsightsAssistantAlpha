import type { AssistantAgent } from '@/api/types'

export const AGENT_LABELS: Record<AssistantAgent, string> = {
  supervisor: 'Supervisor',
  external_data_agent: 'External data agent',
  internal_data_agent: 'Internal data agent',
  relationship_notes_agent: 'Relationship notes agent',
}
