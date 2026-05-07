import type { Config } from 'jest';

const config: Config = {
  testEnvironment: 'jsdom',
  // Default Jest patterns include *.spec.ts and **/*.spec.ts — Playwright lives in e2e/ and must not run under Jest.
  testPathIgnorePatterns: [
    '/node_modules/',
    '<rootDir>/e2e/',
    '<rootDir>/playwright-report/',
    '<rootDir>/test-results/',
  ],
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  transform: {
    '^.+\\.tsx?$': 'ts-jest',
  },
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/$1',
  },
};

export default config;
