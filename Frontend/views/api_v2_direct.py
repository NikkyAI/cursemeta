"""
Direct (but cached) access to (a subset of) the internal Curse API.

In the case of `GET` endpoints, data is passed via URL parameters.
In the case of `POST` endpoints, data must be provided via a `application/json` encoded body.

There is a typo in the API. It is present in the underlying API and is not corrected here.
The key `GameVesion` is missing an `r` (present in `GameVersionLatestFiles`).

The fingerprint algorithm used is a MurmurHash2, but with whitespace normalized. [Reference.](https://github.com/thiakil/CurseApi/blob/master/src/main/java/com/thiakil/curseapi/Murmur2Hash.java)
"""
import collections
import flask
import zeep.xsd.types

import werkzeug.exceptions as exceptions

from .. import app
from .. import curse
from ..helpers import Documentation
from ..helpers import to_json_response
from ..helpers import cache

URL_PREFIX = '/api/v2/direct'
WHITELIST = [
    'GetAddOn',
    'GetRepositoryMatchFromSlug',
    # 'GetChangeLog',
    'v2GetChangeLog',
    # 'GetAddOnDescription',
    'v2GetAddOnDescription',
    'GetAddOnFile',
    # 'GetAddOns',
    'v2GetAddOns',
    # 'GetFingerprintMatches',
    'v2GetFingerprintMatches',
    'GetFuzzyMatches',
    'HealthCheck',
    'ServiceHealthCheck',
    'CacheHealthCheck',
    'GetAllFilesForAddOn',
    'GetAddOnFiles',
]

DOCS = collections.OrderedDict()
_TYPES = {
    str: 'string',
    int: 'int',
    float: 'float',
}

DOCS['API Root'] = Documentation(['GET ' + URL_PREFIX], {}, {'status': 'string (OK = good)', 'message': 'string|null', 'apis': {'<Endpoint name>': {'inp': '<Input type>', 'outp': '<Output type>', 'rules': ['METHOD + template url'], 'extra': 'string|null'}}})


@app.route(URL_PREFIX)
@cache(None)
def api_v2_direct():
    # noinspection PyProtectedMember
    return to_json_response({
        'status': 'OK',
        'message': None,
        'apis': {k: v._asdict() for k, v in DOCS.items()},
    })


def resolve_types(t: zeep.xsd.Any):
    if isinstance(t, zeep.xsd.AnySimpleType):
        return t.name
    elif isinstance(t, zeep.xsd.ComplexType):
        if t.name.startswith('ArrayOf') and len(t.elements) == 1:
            return [resolve_types(t.elements[0][1].type)]
        return collections.OrderedDict((k, resolve_types(v.type)) for k, v in t.elements)
    else:
        raise ValueError('Illegal type')

# todo: Handle errors more gracefully (convert exceptions/errors into HTTP exceptions)


def get_call(n):
    @cache()
    def _f(**kwargs):
        return to_json_response(getattr(curse.service, n)(**kwargs))
    return _f


def post_call(n):
    @cache()
    def _f():
        data = flask.request.get_json()
        if data is None:
            raise exceptions.BadRequest('No JSON data provided.')
        if isinstance(data, dict):
            return to_json_response(getattr(curse.service, n)(**data))
        if isinstance(data, (list, tuple)):
            return to_json_response(getattr(curse.service, n)(*data))
        return to_json_response(getattr(curse.service, n)(data))
    return _f


def _register():
    for name in curse.operations:
        if name not in WHITELIST:
            continue
        service = getattr(curse.service, name)

        parameters = collections.OrderedDict((k, resolve_types(t.type)) for k, t in service.parameters)
        output = resolve_types(service.output)

        # POST is always available
        post_rule = '/'.join((URL_PREFIX, name))
        post_endpoint = '_'.join((URL_PREFIX, name, 'POST')).replace('/', '_').lower()
        app.add_url_rule(rule=post_rule, endpoint=post_endpoint, view_func=post_call(name), methods=['POST'])
        rules = ['POST ' + post_rule]

        # GET only if parameters are 'simple'
        if all(map(lambda x: isinstance(x, str), parameters.values())):
            parameter_types = []
            for k, t in service.parameters:
                parameters[k] = resolve_types(t.type)
                # Idk if this is a good idea, now it will only accept the first type
                t = t.type.accepted_types[0]
                parameter_types.append('<{}:{}>'.format(_TYPES[t], k) if t in _TYPES else '<{}>'.format(k))

            get_rule = '/'.join((URL_PREFIX, name, *parameter_types))
            get_endpoint = '_'.join((URL_PREFIX, name, 'GET')).replace('/', '_').lower()
            app.add_url_rule(rule=get_rule, endpoint=get_endpoint, view_func=get_call(name), methods=['GET'])
            rules.insert(0, 'GET ' + get_rule)

        DOCS[name] = Documentation(rules=rules, inp=parameters, outp=output)


_register()
