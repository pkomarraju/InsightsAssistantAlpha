import type { ApiClient } from '@/api/client'
import type { AssistantRepository } from '@/api/repositories/types'
import type { AssistantMessage } from '@/api/types'

/**
 * Real HTTP-backed AssistantRepository, talking to
 * src/insights_assistant/api/server.py, which threads the full history
 * into agents/orchestrator.py's supervisor.ainvoke on every turn (see
 * orchestrator.run(question, history)) -- a real multi-turn conversation,
 * not per-message pattern matching like the mock.
 */
export function createHttpAssistantRepository(client: ApiClient): AssistantRepository {
  return {
    async getHistory() {
      return client.get<AssistantMessage[]>('/assistant/history')
    },

    async sendMessage(content: string, history: AssistantMessage[]) {
      return client.post<AssistantMessage>('/assistant/chat', {
        content,
        history: history.map((m) => ({ role: m.role, content: m.content })),
      })
    },
  }
}
