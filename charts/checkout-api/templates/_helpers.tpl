{{- define "checkout-api.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "checkout-api.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "checkout-api.labels" -}}
app.kubernetes.io/name: {{ include "checkout-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "checkout-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "checkout-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "checkout-api.postgresName" -}}
{{- printf "%s-postgres" (include "checkout-api.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "checkout-api.dbHost" -}}
{{- if .Values.postgres.enabled -}}
{{- include "checkout-api.postgresName" . -}}
{{- else -}}
{{- required "database.host is required when postgres.enabled is false" .Values.database.host -}}
{{- end -}}
{{- end -}}

{{- define "checkout-api.dbSecretName" -}}
{{- if .Values.database.existingSecret -}}
{{- .Values.database.existingSecret -}}
{{- else -}}
{{- printf "%s-db" (include "checkout-api.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "checkout-api.databaseUrl" -}}
{{- printf "postgresql+psycopg://%s:$(DB_PASSWORD)@%s:%v/%s" .Values.postgres.username (include "checkout-api.dbHost" .) (.Values.database.port | default 5432) .Values.postgres.database -}}
{{- end -}}
