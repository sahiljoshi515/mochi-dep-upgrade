from .checks import result, tail_problem


def verify_input(value):
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    problem = tail_problem(output_value.tail)
    if problem:
        return result(False, problem)
    if output_value.ok != output_value.wheel.endswith(".whl"):
        return result(False, "ok does not match the wheel")
    if output_value.seconds < 0:
        return result(False, "seconds is negative")
    return result(True, "build reported", ok=output_value.ok)
