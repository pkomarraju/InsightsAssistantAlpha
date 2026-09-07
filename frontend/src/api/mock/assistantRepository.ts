import type { AssistantCitation, AssistantMessage } from '@/api/types'
import type { AssistantRepository } from '@/api/repositories/types'
import { delay } from '@/api/mock/latency'
import { companies, relationshipNotes, relationshipSnapshots, riskAssessments } from '@/api/mock/seed'

/**
 * Simulates the three-agent supervisor pipeline in agents/orchestrator.py:
 * routes a question toward the relationship-notes, internal-data, or
 * external-data agent based on keywords, and answers using the same
 * transcribed evidence the mock repositories use elsewhere.
 */

function findCompany(question: string) {
  const lower = question.toLowerCase()
  return companies.find(
    (c) => lower.includes(c.companyName.toLowerCase()) || lower.includes(c.ticker.toLowerCase()),
  )
}

function buildResponse(question: string): { content: string; citations: AssistantCitation[]; activeAgent: AssistantMessage['activeAgent'] } {
  const lower = question.toLowerCase()
  const company = findCompany(question)

  if (lower.includes('at risk') || lower.includes('risk')) {
    const atRiskNotes = relationshipNotes.filter(
      (n) => n.riskFlag === 'at_risk' && (!company || n.companyCode === company.companyId),
    )
    if (atRiskNotes.length > 0) {
      const byCompany = new Map<string, typeof atRiskNotes>()
      for (const note of atRiskNotes) {
        const list = byCompany.get(note.companyCode) ?? []
        list.push(note)
        byCompany.set(note.companyCode, list)
      }
      const lines = [...byCompany.entries()].map(([, notes]) => {
        const latest = notes.sort((a, b) => b.noteDate.localeCompare(a.noteDate))[0]
        return `- **${latest.companyName}** — flagged at risk by ${latest.relationshipManager} (${latest.noteDate}, ${latest.noteId}).`
      })
      return {
        content: `Relationship managers have explicitly flagged the following as currently at risk:\n\n${lines.join('\n')}`,
        citations: [...byCompany.entries()].map(([, notes]) => {
          const latest = notes.sort((a, b) => b.noteDate.localeCompare(a.noteDate))[0]
          return { sourceAgent: 'relationship_notes_agent' as const, evidenceCode: latest.noteId, label: `${latest.companyName} RM note` }
        }),
        activeAgent: 'relationship_notes_agent',
      }
    }
    return {
      content: 'No relationship-manager notes in scope explicitly flag a current relationship-level risk.',
      citations: [],
      activeAgent: 'relationship_notes_agent',
    }
  }

  if (company) {
    const snapshot = relationshipSnapshots.find((s) => s.companyId === company.companyId)
    const risk = riskAssessments.filter((r) => r.companyId === company.companyId).sort((a, b) => b.asOfDate.localeCompare(a.asOfDate))[0]
    if (snapshot) {
      return {
        content: `**${company.companyName}** relationship status is **${snapshot.relationshipStatus.replace('_', ' ')}** as of ${snapshot.asOfDate}. Annual relationship revenue is $${(snapshot.currentAnnualRevenue / 1_000_000).toFixed(0)}M (${snapshot.yoyGrowthPct >= 0 ? '+' : ''}${snapshot.yoyGrowthPct.toFixed(1)}% YoY).${risk ? ` Relationship risk score is ${risk.relationshipRiskScore.toFixed(1)} (${risk.riskTrend}).` : ''}`,
        citations: [
          { sourceAgent: 'internal_data_agent', evidenceCode: `REL_${company.companyId.split('_')[1]}`, label: 'Relationship snapshot' },
          ...(risk ? [{ sourceAgent: 'internal_data_agent' as const, evidenceCode: risk.riskId, label: 'Quarterly risk assessment' }] : []),
        ],
        activeAgent: 'internal_data_agent',
      }
    }
  }

  return {
    content:
      "I can answer questions about relationship health, at-risk flags from RM notes, and public filing signals for the ten companies in scope. Try asking, for example, \"Which companies has the relationship manager flagged at risk?\" or \"What is Amazon's relationship status?\"",
    citations: [],
    activeAgent: 'supervisor',
  }
}

const seedMessage: AssistantMessage = {
  id: 'MSG_0',
  role: 'assistant',
  content:
    "Hello, I'm the Insights Assistant. Ask me about relationship health, at-risk flags, or filing-based signals for a client, and I'll route your question to the right specialist and cite the evidence.",
  createdAt: '2026-08-20T13:00:00Z',
  activeAgent: 'supervisor',
}

export function createMockAssistantRepository(): AssistantRepository {
  return {
    async getHistory() {
      await delay(200)
      return [seedMessage]
    },

    async sendMessage(content: string) {
      await delay(700)
      const { content: replyContent, citations, activeAgent } = buildResponse(content)
      return {
        id: `MSG_${Date.now()}`,
        role: 'assistant',
        content: replyContent,
        createdAt: new Date().toISOString(),
        citations,
        activeAgent,
      }
    },
  }
}
