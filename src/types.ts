// Shared data contracts. Every screen, lib and data file conforms to these. Do not edit without updating DESIGN.md.

export type BikeId = string

export interface Bike {
  id: BikeId            // "ktm-390-duke-2024"
  make: string          // "KTM"
  model: string         // "390 Duke"
  year: number          // 2024
  market: string        // "EU" | "US"
  manualId: string | null // null = no manual indexed yet
  vins?: string[]       // mock VIN prefixes (first 9-11 chars) that decode to this bike
  cues?: string[]       // mock visual cues for photo identification
}

export interface OutlineNode {
  title: string
  page: number          // 1-based PDF page index
  children?: OutlineNode[]
}

export interface Highlight {
  page: number          // 1-based PDF page index
  x: number; y: number; w: number; h: number // fractions of page width/height, origin top-left
}

export interface Section {
  id: string            // "front-brake-pads"
  title: string         // exactly as printed in the manual
  chapter: string       // top-level outline title it belongs to
  pageStart: number     // 1-based, inclusive
  pageEnd: number       // 1-based, inclusive
  keywords: string[]    // lowercase words/phrases a user might say
  highlights: Highlight[]
  partIds?: string[]
  related?: string[]    // section ids worth showing after this one (torque table, tools)
}

export interface Part {
  id: string
  name: string          // as printed in the manual
  spec: string          // "SAE 10W-50, JASO T903 MA2" / "NGK LMAR8AI-9"
  page: number          // where the spec is printed
  oem?: string          // OEM part number if printed
  links: { shop: string; url: string }[]
}

export interface Manual {
  id: string            // "ktm-390-duke-2024-om-en"
  bikeIds: BikeId[]
  file: string          // "/manuals/ktm-390-duke-2024-om-en.pdf"
  pages: number
  title: string         // as printed on the cover
  source: string        // official URL the PDF was downloaded from
  outline: OutlineNode[]
  sections: Section[]
  parts: Part[]
}

export interface Match {
  section: Section
  score: number         // 0..1
}

export interface Candidate {
  bikeId: BikeId
  confidence: number    // 0..1
}
