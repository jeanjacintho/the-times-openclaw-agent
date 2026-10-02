---
type: Schema
root: projects/thetimes
required: [type, title, description, category, tags, sources, created, updated]
fields:
  type: {enum: [Project, Synthesis, Edition]}
  paper: {type: link}
  date: {type: date}
tables:
  - into: paper
    section: "## Editions"
    match: {type: Edition}
    sort_by: date
    columns: [title, description]
title: projects/thetimes schema
category: meta
tags: [schema]
sources: []
created: {today}
updated: {today}
---
# projects/thetimes/

The Times writes here. Every page links back to the paper's page with
`paper:`, so `wiki index` lists the editions there.
