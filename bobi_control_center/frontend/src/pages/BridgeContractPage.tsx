/**
 * What each `script.bobi_cc_*` must do, and which ones exist yet.
 *
 * A developer's screen rather than a household one, and it is here rather than
 * in a document because a document goes stale the moment a family is added.
 * This reads the same declarations the calling code reads, so what it shows is
 * what this build actually sends.
 *
 * It carries no household data at all — service names, field names, validation
 * rules and risk ratings.
 */

import { useState } from 'react';
import { CheckCircle2, CircleDashed, Copy } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { AdvancedDisclosure } from '@/components/ui/Advanced';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, SectionTitle } from '@/components/ui/Card';
import { Chip } from '@/components/ui/Field';
import { PageHeader } from '@/components/ui/PageHeader';
import { QueryBoundary } from '@/components/state/QueryBoundary';

interface BridgeField {
  name: string;
  type: string;
  note: string;
}

interface BridgeServiceContract {
  name: string;
  kind: 'read' | 'write';
  purpose: string;
  resource: string | null;
  operations: string[];
  inputs: BridgeField[];
  outputs: string;
  validation: string[];
  verification: string;
  risk: string;
  operation_risk: Record<string, string>;
}

interface BridgeContract {
  app_version: string;
  implemented: string[];
  missing: string[];
  services: BridgeServiceContract[];
  common_commit_inputs: BridgeField[];
  common_commit_outputs: BridgeField[];
  never_called_domains: string[];
  never_requested: string[];
  risk_to_role: Record<string, string>;
}

const RISK_TONES: Record<string, BadgeTone> = {
  read_only: 'muted',
  low: 'neutral',
  medium: 'info',
  high: 'warning',
  destructive: 'error',
};

type Filter = 'missing' | 'all';

export function BridgeContractPage() {
  const query = useQuery({
    queryKey: ['bridge-contract'],
    queryFn: () => api.get<BridgeContract>('/api/bobi/manage/bridge-contract'),
  });
  const [filter, setFilter] = useState<Filter>('missing');
  const [copied, setCopied] = useState(false);

  return (
    <div className="space-y-4">
      <PageHeader
        title="חוזה הגשרים"
        description="מה כל script.bobi_cc_* צריך לקבל, להחזיר ולוודא."
      />

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחנו לטעון את חוזה הגשרים"
        onRetry={() => void query.refetch()}
      >
        {(contract) => {
          const missing = new Set(contract.missing);
          const shown = contract.services.filter(
            (service) => filter === 'all' || missing.has(service.name),
          );

          return (
            <div className="space-y-4">
              <Card>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="ok" dot>
                    {contract.implemented.length} קיימים
                  </Badge>
                  <Badge tone={contract.missing.length > 0 ? 'warning' : 'muted'} dot>
                    {contract.missing.length} חסרים
                  </Badge>
                  <Badge tone="muted">גרסה {contract.app_version}</Badge>
                </div>
                <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
                  "חסר" נקבע מול החוזה החי: משאב שהגשר לא מכריז עליו, או שמכריז עליו בלי
                  פעולות, מופיע כאן עם שירות ה-commit שלו חסר.
                </p>
                {contract.missing.length > 0 ? (
                  <Button
                    className="mt-3"
                    variant="secondary"
                    onClick={() => {
                      void navigator.clipboard
                        ?.writeText(contract.missing.join('\n'))
                        .then(() => setCopied(true))
                        .catch(() => setCopied(false));
                    }}
                  >
                    <Copy aria-hidden className="h-4 w-4" />
                    {copied ? 'הועתק' : 'העתק את רשימת החסרים'}
                  </Button>
                ) : null}
              </Card>

              <div className="flex flex-wrap gap-2">
                <Chip selected={filter === 'missing'} onClick={() => setFilter('missing')}>
                  חסרים בלבד
                </Chip>
                <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>
                  כל {contract.services.length} השירותים
                </Chip>
              </div>

              {shown.length === 0 ? (
                <Card>
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    כל הגשרים שהאפליקציה קוראת להם קיימים ב-Home Assistant.
                  </p>
                </Card>
              ) : (
                shown.map((service) => (
                  <ServiceCard
                    key={service.name}
                    service={service}
                    implemented={!missing.has(service.name)}
                  />
                ))
              )}

              <section>
                <SectionTitle>נשלח בכל commit</SectionTitle>
                <Card>
                  <FieldTable fields={contract.common_commit_inputs} />
                </Card>
              </section>

              <section>
                <SectionTitle>מוחזר מכל commit</SectionTitle>
                <Card>
                  <FieldTable fields={contract.common_commit_outputs} />
                </Card>
              </section>

              <section>
                <SectionTitle>מה לעולם לא נקרא</SectionTitle>
                <Card>
                  <p className="mb-2 text-sm text-slate-600 dark:text-slate-300">
                    דומיינים שהאפליקציה לא קוראת להם בשום מצב:
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {contract.never_called_domains.map((domain) => (
                      <Badge key={domain} tone="muted">
                        {domain}.*
                      </Badge>
                    ))}
                  </div>
                  <ul className="mt-4 space-y-1 text-sm text-slate-600 dark:text-slate-300">
                    {contract.never_requested.map((entry) => (
                      <li key={entry}>• {entry}</li>
                    ))}
                  </ul>
                </Card>
              </section>

              <section>
                <SectionTitle>סיכון והרשאה</SectionTitle>
                <Card>
                  <ul className="space-y-1 text-sm text-slate-700 dark:text-slate-200">
                    {Object.entries(contract.risk_to_role).map(([risk, role]) => (
                      <li key={risk} className="flex items-center justify-between gap-4">
                        <Badge tone={RISK_TONES[risk] ?? 'neutral'}>{risk}</Badge>
                        <span>{role}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              </section>
            </div>
          );
        }}
      </QueryBoundary>
    </div>
  );
}

function ServiceCard({
  service,
  implemented,
}: {
  service: BridgeServiceContract;
  implemented: boolean;
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-sm font-medium text-slate-900 dark:text-slate-100">
            script.{service.name}
          </p>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{service.purpose}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Badge tone={service.kind === 'write' ? 'warning' : 'muted'}>
            {service.kind === 'write' ? 'כתיבה' : 'קריאה'}
          </Badge>
          <Badge tone={RISK_TONES[service.risk] ?? 'neutral'}>{service.risk}</Badge>
          {implemented ? (
            <CheckCircle2 aria-label="קיים" className="h-4 w-4 text-emerald-600" />
          ) : (
            <CircleDashed aria-label="חסר" className="h-4 w-4 text-amber-600" />
          )}
        </div>
      </div>

      {service.operations.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {service.operations.map((operation) => (
            <Badge key={operation} tone={RISK_TONES[service.operation_risk[operation] ?? '']}>
              {operation} · {service.operation_risk[operation] ?? 'low'}
            </Badge>
          ))}
        </div>
      ) : null}

      {/*
        The specification, folded away.

        Thirty-three services printed in full made this page forty thousand
        pixels tall — some fifty screens on a phone — which is not a reference
        anyone reads, it is a document you scroll past. The header above stays
        visible so the list can be scanned for the service you want; its
        contract opens when you ask for it.
      */}
      <AdvancedDisclosure title="החוזה המלא">
        {service.inputs.length > 0 ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">קלט</p>
            <FieldTable fields={service.inputs} />
          </div>
        ) : null}

        {service.outputs ? (
          <div className="mt-4">
            <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">פלט</p>
            <pre
              dir="ltr"
              className="overflow-x-auto rounded-xl bg-slate-50 p-3 text-xs text-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
            >
              {service.outputs}
            </pre>
          </div>
        ) : null}

        {service.validation.length > 0 ? (
          <div className="mt-4">
            <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">ולידציה</p>
            <ul className="space-y-1 text-sm text-slate-600 dark:text-slate-300">
              {service.validation.map((rule) => (
                <li key={rule}>• {rule}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {service.verification ? (
          <div className="mt-4">
            <p className="mb-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">אימות</p>
            <p className="text-sm text-slate-600 dark:text-slate-300">{service.verification}</p>
          </div>
        ) : null}
      </AdvancedDisclosure>
    </Card>
  );
}

function FieldTable({ fields }: { fields: BridgeField[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-start text-sm">
        <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
          {fields.map((field) => (
            <tr key={field.name}>
              <td className="py-2 pe-3 align-top font-mono text-xs text-slate-900 dark:text-slate-100">
                {field.name}
              </td>
              <td className="py-2 pe-3 align-top text-xs text-slate-500 dark:text-slate-400">
                {field.type}
              </td>
              <td className="py-2 align-top text-slate-600 dark:text-slate-300">{field.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
