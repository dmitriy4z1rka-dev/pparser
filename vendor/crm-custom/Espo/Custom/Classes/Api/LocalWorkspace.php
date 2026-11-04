<?php

namespace Espo\Custom\Classes\Api;

use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface;
use Slim\Psr7\Response;

/** Open the loopback-only workspace without asking the operator for credentials. */
class LocalWorkspace implements MiddlewareInterface
{
    public function process(ServerRequestInterface $request, RequestHandlerInterface $handler): ResponseInterface
    {
        $host = strtolower($request->getUri()->getHost());
        $origin = $request->getHeaderLine('Origin');
        $uri = $request->getUri();
        $originScheme = $origin ? parse_url($origin, PHP_URL_SCHEME) : null;
        $originHost = $origin ? parse_url($origin, PHP_URL_HOST) : null;
        $originPort = $origin ? (parse_url($origin, PHP_URL_PORT) ?: ($originScheme === 'https' ? 443 : 80)) : null;
        $port = $uri->getPort() ?: ($uri->getScheme() === 'https' ? 443 : 80);
        if (!in_array($host, ['localhost', '127.0.0.1', '::1', 'espocrm'], true) ||
            ($origin && ($originHost !== $host || $originScheme !== $uri->getScheme() || $originPort !== $port)) ||
            $request->getHeaderLine('Sec-Fetch-Site') === 'cross-site') {
            return new Response(403);
        }

        // Keep the restricted parser API key separate. Browser sessions use the
        // same internal identity; none of its credentials are sent to the client.
        if (!$request->hasHeader('X-Api-Key') && !$request->hasHeader('Authorization') &&
            !$request->hasHeader('Espo-Authorization')) {
            $username = getenv('ESPOCRM_ADMIN_USERNAME');
            $password = getenv('ESPOCRM_ADMIN_PASSWORD');
            if (!$username || !$password) {
                return new Response(503);
            }
            $request = $request->withHeader('Espo-Authorization', base64_encode($username . ':' . $password));
        }

        return $handler->handle($request);
    }
}
