"""
Offline stand-in for the `genlayer` SDK, used only by the test suite.

It provides the small surface AnswerArena touches: storage types that start
empty, no-op public decorators, a settable gl.message, patchable
gl.nondet.web.render and gl.nondet.exec_prompt, gl.vm.run_nondet_unsafe with
a JSON round trip of the leader result and a validator that receives
gl.vm.Return, and an EVM interface whose transfers are recorded.

It does not simulate the network, real models or multi-validator consensus;
tests drive those by patching and by calling the validator directly.
"""
import json

__all__ = ["gl", "TreeMap", "DynArray", "u256", "Address"]


class _Generic:
    def __class_getitem__(cls, item):
        return cls


class TreeMap(_Generic, dict):
    pass


class DynArray(_Generic, list):
    pass


class u256(int):
    def __new__(cls, value=0):
        number = int(value)
        if number < 0 or number >= 2 ** 256:
            raise OverflowError("u256 out of range")
        return super().__new__(cls, number)


class Address:
    def __init__(self, value):
        text = str(value)
        if not text.startswith("0x") or len(text) != 42:
            raise ValueError(f"invalid address: {text!r}")
        int(text[2:], 16)
        self._value = text

    def __str__(self):
        return self._value

    def __eq__(self, other):
        return str(self).lower() == str(other).lower()

    def __hash__(self):
        return hash(str(self).lower())


class UserError(Exception):
    pass


class _Return:
    def __init__(self, calldata):
        self.calldata = calldata


class _Vm:
    UserError = UserError
    Return = _Return
    validator_hook = None

    @staticmethod
    def run_nondet_unsafe(leader_fn, validator_fn):
        result = json.loads(json.dumps(leader_fn(), allow_nan=False))
        hook = getattr(gl.vm, "validator_hook", None)
        if hook is not None:
            hook(result, validator_fn)
        elif not validator_fn(_Return(result)):
            raise UserError("validators rejected the leader result")
        return result


class _Write:
    def __call__(self, fn):
        return fn

    @staticmethod
    def payable(fn):
        return fn


class _Public:
    write = _Write()

    @staticmethod
    def view(fn):
        return fn


class _Web:
    @staticmethod
    def render(url, mode="text"):
        raise NotImplementedError("patch gl.nondet.web.render in tests")


class _Nondet:
    web = _Web()

    @staticmethod
    def exec_prompt(prompt, response_format="text"):
        raise NotImplementedError("patch gl.nondet.exec_prompt in tests")


class _Message:
    sender_address = None
    value = u256(0)


class _Contract:
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        for klass in reversed(cls.__mro__):
            for name, annotation in vars(klass).get("__annotations__", {}).items():
                if isinstance(annotation, type) and issubclass(annotation, (TreeMap, DynArray)):
                    setattr(instance, name, annotation())
                elif annotation is u256:
                    setattr(instance, name, u256(0))
        instance.balance = u256(0)
        return instance

    def __init__(self, *args, **kwargs):
        pass


class _Proxy:
    def __init__(self, address):
        self.address = address

    def emit_transfer(self, value):
        _Evm.transfers.append({"to": str(self.address).lower(), "value": int(value)})


class _Evm:
    transfers = []

    @staticmethod
    def contract_interface(cls):
        return _Proxy


class _GL:
    Contract = _Contract
    public = _Public()
    nondet = _Nondet()
    vm = _Vm()
    message = _Message()
    message_raw = {}
    evm = _Evm()


gl = _GL()
