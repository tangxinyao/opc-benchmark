"""Harbor agent 适配器。一个子模块一种 agent。

hermes 只是其中一种——换别的 agent 来跑同一套题，在这里加一个模块就行，
题目和判分器一行都不用动。

    harbor run -p tasks --agent opc.agents.hermes:Hermes -m deepseek/deepseek-chat
"""
