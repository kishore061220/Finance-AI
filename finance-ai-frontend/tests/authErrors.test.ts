/**
 * Auth error messaging.
 *
 * These assertions lock in the two properties that matter for security and
 * usability: account-existence is never revealed, and a raw Firebase string is
 * never shown to the user.
 */

import { describe, expect, it } from 'vitest'

import { describeAuthFailure, describeFirebaseError, firebaseErrorCode } from '@/lib/authErrors'
import { ApiError } from '@/lib/api'

function firebaseError(code: string): Error {
  return Object.assign(new Error(`Firebase: Error (${code}).`), { code })
}

describe('firebaseErrorCode', () => {
  it('extracts an auth code', () => {
    expect(firebaseErrorCode(firebaseError('auth/invalid-credential'))).toBe('auth/invalid-credential')
  })

  it('ignores non-auth errors', () => {
    expect(firebaseErrorCode(new Error('nope'))).toBeNull()
    expect(firebaseErrorCode(Object.assign(new Error('x'), { code: 'custom/thing' }))).toBeNull()
    expect(firebaseErrorCode('not-an-error')).toBeNull()
  })
})

describe('describeFirebaseError', () => {
  it('never reveals whether the account exists', () => {
    const wrongPassword = describeFirebaseError(firebaseError('auth/wrong-password'))
    const userNotFound = describeFirebaseError(firebaseError('auth/user-not-found'))
    const invalidCredential = describeFirebaseError(firebaseError('auth/invalid-credential'))

    expect(invalidCredential).toBe(wrongPassword)
    expect(invalidCredential).toBe(userNotFound)
    expect(invalidCredential).toMatch(/email or password is incorrect/i)
  })

  it('explains a blocked popup', () => {
    expect(describeFirebaseError(firebaseError('auth/popup-blocked'))).toMatch(/popup was blocked/i)
  })

  it('returns null for a non-Firebase error', () => {
    expect(describeFirebaseError(new Error('plain'))).toBeNull()
  })
})

describe('describeAuthFailure', () => {
  it('prefers the Firebase explanation when present', () => {
    expect(describeAuthFailure(firebaseError('auth/invalid-credential'))).toMatch(
      /email or password is incorrect/i,
    )
  })

  it('explains an API rejection after Firebase accepted the sign-in', () => {
    const rejected = new ApiError('Invalid or expired authentication token.', 401, '', [])
    expect(describeAuthFailure(rejected)).toMatch(/API rejected the session/i)
  })

  it('passes a network message through unchanged', () => {
    const message = 'Could not reach the server. Check that the API is running.'
    const offline = new ApiError(message, 0, message, [])
    expect(describeAuthFailure(offline)).toMatch(/Could not reach the server/i)
  })

  it('falls back to a generic message', () => {
    expect(describeAuthFailure(undefined)).toMatch(/could not complete sign-in/i)
  })
})
