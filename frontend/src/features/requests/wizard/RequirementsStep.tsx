import type { InsightCategory, ResearchRequest } from '@/api/types'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { CATEGORY_OPTIONS, RANKING_OPTIONS } from '@/features/requests/wizard/wizardState'

type RankingCriterion = ResearchRequest['insightRequirements']['rankingCriteria'][number]

interface RequirementsStepProps {
  totalCount: number
  categories: { categoryId: InsightCategory; minimumCount: number }[]
  rankingCriteria: RankingCriterion[]
  generalSearchPrompt: string
  onChange: (patch: Partial<{
    totalCount: number
    categories: { categoryId: InsightCategory; minimumCount: number }[]
    rankingCriteria: RankingCriterion[]
    generalSearchPrompt: string
  }>) => void
}

export function RequirementsStep({
  totalCount,
  categories,
  rankingCriteria,
  generalSearchPrompt,
  onChange,
}: RequirementsStepProps) {
  const toggleCategory = (categoryId: InsightCategory) => {
    const exists = categories.some((c) => c.categoryId === categoryId)
    onChange({
      categories: exists
        ? categories.filter((c) => c.categoryId !== categoryId)
        // minimumCount is always 0: a selected focus area is banker
        // interest, never a quota the assistant must manufacture insights
        // to hit -- see totalCount's own "target, not requirement" framing
        // below and wizardState.ts's initialWizardState.
        : [...categories, { categoryId, minimumCount: 0 }],
    })
  }

  const toggleRanking = (criterion: RankingCriterion) => {
    onChange({
      rankingCriteria: rankingCriteria.includes(criterion)
        ? rankingCriteria.filter((c) => c !== criterion)
        : [...rankingCriteria, criterion],
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-40">
        <Label htmlFor="totalCount" className="mb-1.5 block text-xs font-medium text-ink-muted">
          Target insight count
        </Label>
        <Input
          id="totalCount"
          type="number"
          min={1}
          max={100}
          value={totalCount}
          onChange={(e) => onChange({ totalCount: Number(e.target.value) || 1 })}
        />
      </div>

      <section>
        <h3 className="mb-1 text-sm font-semibold text-ink">Insight focus areas</h3>
        <p className="mb-2 text-xs text-ink-muted">
          Select the areas most relevant to this request. The assistant may return fewer insights when
          the available evidence does not support the target count.
        </p>
        <div className="flex flex-col gap-2">
          {CATEGORY_OPTIONS.map((option) => {
            const active = categories.some((c) => c.categoryId === option.id)
            return (
              <label
                key={option.id}
                className="flex items-start gap-3 rounded-md border border-border bg-surface-raised p-3 text-sm hover:bg-surface-hover has-[[data-state=checked]]:border-accent-soft-border has-[[data-state=checked]]:bg-accent-soft"
              >
                <Checkbox checked={active} onCheckedChange={() => toggleCategory(option.id)} />
                <span>
                  <span className="block font-medium text-ink">{option.label}</span>
                  <span className="block text-xs text-ink-faint">{option.description}</span>
                </span>
              </label>
            )
          })}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-ink">Ranking criteria</h3>
        <div className="flex flex-wrap gap-4">
          {RANKING_OPTIONS.map((option) => (
            <label key={option.id} className="flex items-center gap-2 text-sm text-ink">
              <Checkbox checked={rankingCriteria.includes(option.id)} onCheckedChange={() => toggleRanking(option.id)} />
              {option.label}
            </label>
          ))}
        </div>
      </section>

      <section>
        <Label htmlFor="prompt" className="mb-1.5 block text-sm font-semibold text-ink">
          Search prompt
        </Label>
        <Textarea
          id="prompt"
          value={generalSearchPrompt}
          onChange={(e) => onChange({ generalSearchPrompt: e.target.value })}
          placeholder="Describe what the research should focus on, e.g. material changes in strategy, liquidity, or disclosed risk…"
          rows={4}
        />
      </section>
    </div>
  )
}
