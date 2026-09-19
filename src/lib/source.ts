import type { Bike, Candidate, Manual, Match } from '../types'
import { bikes as mockBikes, manualFor } from '../data'
import { match } from './match'
import { fromPhoto, fromVin } from './identify'

// Owner: frontend-api agent. Mock implementation; switch to the backend when VITE_API_URL is set.

export const online = Boolean(import.meta.env.VITE_API_URL)

export async function loadBikes(): Promise<Bike[]> {
  return mockBikes
}

export async function loadManual(bike: Bike): Promise<Manual | null> {
  return manualFor(bike)
}

export async function ask(manual: Manual, query: string): Promise<Match[]> {
  return match(manual, query)
}

export async function identifyPhoto(bikes: Bike[], file: File): Promise<Candidate[]> {
  return fromPhoto(bikes, file)
}

export async function identifyVin(bikes: Bike[], vin: string): Promise<Bike | null> {
  return fromVin(bikes, vin)
}
