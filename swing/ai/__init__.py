"""Agents IA (phase 2), en mode OBSERVATION : ils produisent des avis enregistrés
dans data/ai/ mais ne modifient jamais le portefeuille de la stratégie.

  - news       : agent Actualités (Claude Haiku) — titres de presse classés par ticker
  - themes     : détecteur de signaux faibles (code, sans IA) — thèmes en accélération
  - macro      : agent Macro (Claude Sonnet) — régime de marché, hebdomadaire
  - committee  : Comité (Claude Opus) — revue des positions cibles en fin de mois
  - llm        : appels à l'API Claude, réponses JSON validées, suivi des coûts, plafond mensuel
"""
