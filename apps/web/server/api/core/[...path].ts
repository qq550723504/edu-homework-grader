import { getRequestHeaders, getRouterParam, readRawBody, setResponseHeader, setResponseStatus } from 'h3'

import { accessTokenForCoreApi } from '../../utils/core-api'
import { requireCsrfToken } from '../../utils/csrf'

const excludedRequestHeaders = new Set(['authorization', 'content-length', 'cookie', 'host'])

export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event)
  const path = getRouterParam(event, 'path')
  if (!path?.startsWith('v1/')) {
    throw createError({ statusCode: 404, statusMessage: 'resource not found' })
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(event.method ?? 'GET')) {
    await requireCsrfToken(event)
  }

  const headers = Object.fromEntries(
    Object.entries(getRequestHeaders(event)).filter(([name]) => !excludedRequestHeaders.has(name))
  )
  headers.authorization = `Bearer ${await accessTokenForCoreApi(event)}`
  const response = await fetch(`${config.coreApiBase.replace(/\/$/, '')}/${path}`, {
    body: ['GET', 'HEAD'].includes(event.method ?? 'GET') ? undefined : await readRawBody(event, false),
    headers,
    method: event.method
  })
  if (response.headers.get('content-type')) {
    setResponseHeader(event, 'content-type', response.headers.get('content-type')!)
  }
  setResponseHeader(event, 'cache-control', 'no-store')
  setResponseStatus(event, response.status)
  return response.text()
})
