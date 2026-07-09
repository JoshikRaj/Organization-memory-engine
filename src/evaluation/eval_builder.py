"""
evaluation/eval_builder.py

Builds and manages your evaluation dataset.

Why hand-label questions instead of auto-generating them?
Because auto-generated questions have auto-generated answers —
you can't verify if the answer is actually correct without
checking the source yourself. Hand-labeling 50 questions
takes 2-3 hours but gives you ground truth you can defend
in an interview. That's the difference between a real
benchmark and a fake one.
"""

import logging

from src.storage.database import get_connection

logger = logging.getLogger(__name__)


# ── SEED QUESTIONS ────────────────────────────────────────────────
# These are your 50 starter questions.
# You MUST verify each answer yourself in the Apache Jira/GitHub data.
# Don't guess — look it up and confirm it's there.
# Add more as you find interesting questions in the data.

SEED_QUESTIONS = [

    # ── FACTUAL questions (20) ────────────────────────────────────
    {
        "question": "What is KRaft in Apache Kafka?",
        "expected_answer": "KRaft is Kafka's built-in consensus protocol that replaces ZooKeeper for metadata management, making Kafka self-sufficient without external dependencies.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "kraft",
    },
    {
        "question": "What was ZooKeeper used for in Kafka before KRaft?",
        "expected_answer": "ZooKeeper was used for distributed coordination, storing broker metadata, managing controller election, and maintaining configuration for topics and partitions.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "zookeeper",
    },
    {
        "question": "What does ISR stand for in Kafka?",
        "expected_answer": "ISR stands for In-Sync Replicas — the set of partition replicas that are fully caught up with the leader.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "replication",
    },
    {
        "question": "What is log compaction in Kafka?",
        "expected_answer": "Log compaction is a mechanism that retains only the latest value for each key in a topic, allowing Kafka to act as a changelog or state store rather than just a message queue.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "log compaction",
    },
    {
        "question": "What is a Kafka consumer group?",
        "expected_answer": "A consumer group is a set of consumers that jointly consume a topic, with each partition assigned to exactly one consumer in the group, enabling parallel consumption.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "consumer group",
    },
    {
        "question": "What is tiered storage in Kafka?",
        "expected_answer": "Tiered storage allows Kafka to offload older log segments to cheaper remote storage like S3 or GCS while keeping recent data on local disks, reducing storage costs.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "tiered storage",
    },
    {
        "question": "What is the role of the Kafka controller?",
        "expected_answer": "The controller is a broker responsible for managing partition leadership, handling broker failures, and maintaining cluster metadata.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "controller",
    },
    {
        "question": "What is Kafka Connect?",
        "expected_answer": "Kafka Connect is a framework for connecting Kafka with external systems like databases, key-value stores, and file systems through reusable source and sink connectors.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "kafka connect",
    },
    {
        "question": "What is a Kafka partition?",
        "expected_answer": "A partition is an ordered, immutable sequence of records that is continuously appended to. Topics are split into partitions for parallelism and scalability.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "partition",
    },
    {
        "question": "What is the purpose of consumer offsets in Kafka?",
        "expected_answer": "Consumer offsets track the position of each consumer group in each partition, allowing consumers to resume from where they left off after a restart or failure.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "offsets",
    },
    {
        "question": "What is MirrorMaker in Kafka?",
        "expected_answer": "MirrorMaker is a tool for replicating data between Kafka clusters, typically used for disaster recovery, geographic distribution, or data migration.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "mirrormaker",
    },
    {
        "question": "What is the difference between Kafka Streams and Kafka Connect?",
        "expected_answer": "Kafka Streams is a library for building stream processing applications that transform data within Kafka. Kafka Connect is a framework for moving data between Kafka and external systems.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "kafka streams",
    },
    {
        "question": "What is a Kafka broker?",
        "expected_answer": "A broker is a Kafka server that stores data and serves client requests. Multiple brokers form a Kafka cluster for fault tolerance and scalability.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "broker",
    },
    {
        "question": "What is the purpose of acks in Kafka producer configuration?",
        "expected_answer": "The acks setting controls how many broker acknowledgments the producer requires before considering a request complete. acks=0 means no acknowledgment, acks=1 means leader only, acks=all means all in-sync replicas.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "producer",
    },
    {
        "question": "What is schema registry in Kafka?",
        "expected_answer": "Schema Registry is a service that stores and enforces Avro, JSON, or Protobuf schemas for Kafka messages, ensuring producers and consumers agree on data format.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "schema registry",
    },
    {
        "question": "What is a dead letter queue in Kafka?",
        "expected_answer": "A dead letter queue is a topic where messages that cannot be processed successfully are sent, allowing them to be inspected and reprocessed without blocking the main pipeline.",
        "answer_type": "factual",
        "difficulty": "medium",
        "topic": "dead letter queue",
    },
    {
        "question": "What does replication factor mean in Kafka?",
        "expected_answer": "Replication factor is the number of copies of each partition maintained across brokers. A replication factor of 3 means each partition has one leader and two followers.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "replication",
    },
    {
        "question": "What is exactly-once semantics in Kafka?",
        "expected_answer": "Exactly-once semantics guarantees that each message is processed exactly once even in the presence of failures, using idempotent producers and transactional APIs.",
        "answer_type": "factual",
        "difficulty": "hard",
        "topic": "exactly once",
    },
    {
        "question": "What is a Kafka topic?",
        "expected_answer": "A topic is a named stream of records in Kafka. Producers write to topics and consumers read from them. Topics are divided into partitions for scalability.",
        "answer_type": "factual",
        "difficulty": "easy",
        "topic": "topics",
    },
    {
        "question": "What is the __consumer_offsets topic?",
        "expected_answer": "It is an internal Kafka topic that stores the committed offsets for all consumer groups, replacing the older ZooKeeper-based offset storage.",
        "answer_type": "factual",
        "difficulty": "hard",
        "topic": "offsets",
    },

    # ── DECISION questions (20) ───────────────────────────────────
    {
        "question": "Why did Apache Kafka decide to remove ZooKeeper dependency?",
        "expected_answer": "ZooKeeper added operational complexity, required separate expertise to manage, limited Kafka's scalability for large numbers of partitions, and created a bottleneck for metadata operations.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "zookeeper",
    },
    {
        "question": "What alternatives were considered before choosing KRaft over ZooKeeper?",
        "expected_answer": "The team considered keeping ZooKeeper, using etcd as a replacement, and building on an existing Raft implementation before deciding to build KRaft natively within Kafka.",
        "answer_type": "decision",
        "difficulty": "hard",
        "topic": "kraft",
    },
    {
        "question": "Why was log compaction introduced in Kafka?",
        "expected_answer": "Log compaction was introduced to allow Kafka to serve as a system of record for key-based data, enabling consumers to rebuild state without replaying the entire log history.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "log compaction",
    },
    {
        "question": "Why did Kafka move consumer offset storage from ZooKeeper to an internal topic?",
        "expected_answer": "ZooKeeper was not designed for high-frequency writes. Storing offsets in ZooKeeper caused performance bottlenecks at scale. The internal __consumer_offsets topic handles this more efficiently.",
        "answer_type": "decision",
        "difficulty": "hard",
        "topic": "offsets",
    },
    {
        "question": "Why was tiered storage added to Kafka?",
        "expected_answer": "Tiered storage was added to reduce the cost of retaining large amounts of data on expensive local SSDs, allowing older data to be moved to cheaper object storage like S3.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "tiered storage",
    },
    {
        "question": "Why does Kafka use a pull-based consumer model instead of push?",
        "expected_answer": "Pull-based consumption allows consumers to control their own rate, handle backpressure naturally, and batch messages efficiently. Push-based models can overwhelm slow consumers.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "consumer",
    },
    {
        "question": "Why did Kafka choose Raft consensus for KRaft instead of Paxos?",
        "expected_answer": "Raft is easier to understand, implement, and reason about than Paxos. It has clearer leader election and log replication semantics, reducing implementation complexity.",
        "answer_type": "decision",
        "difficulty": "hard",
        "topic": "kraft",
    },
    {
        "question": "Why does Kafka store messages on disk instead of in memory?",
        "expected_answer": "Disk storage allows Kafka to handle datasets larger than RAM, survive process restarts, and leverage the OS page cache for performance without custom memory management.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "storage",
    },
    {
        "question": "Why was Kafka Connect introduced as a separate framework?",
        "expected_answer": "Kafka Connect standardized the pattern of moving data in and out of Kafka, reducing duplicated connector code across organizations and providing a managed runtime for connectors.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "kafka connect",
    },
    {
        "question": "Why did Kafka add idempotent producers?",
        "expected_answer": "Idempotent producers prevent duplicate messages during retries after network failures, enabling exactly-once delivery semantics at the producer level without application-level deduplication.",
        "answer_type": "decision",
        "difficulty": "hard",
        "topic": "producer",
    },
    {
        "question": "Why was the controller moved into the broker process in KRaft?",
        "expected_answer": "Having a separate controller process added operational overhead. Moving it into the broker reduced the number of components to manage and eliminated ZooKeeper as a dependency for controller election.",
        "answer_type": "decision",
        "difficulty": "hard",
        "topic": "controller",
    },
    {
        "question": "Why does Kafka use sequential disk I/O instead of random access?",
        "expected_answer": "Sequential disk I/O is dramatically faster than random access on spinning disks and still efficient on SSDs. Kafka's append-only log design exploits this for high throughput.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "storage",
    },
    {
        "question": "Why did Kafka introduce consumer group rebalancing?",
        "expected_answer": "Rebalancing allows partition assignments to be redistributed automatically when consumers join or leave a group, ensuring all partitions are always being consumed without manual intervention.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "consumer group",
    },
    {
        "question": "Why was MirrorMaker 2 created to replace MirrorMaker 1?",
        "expected_answer": "MirrorMaker 1 had no support for offset translation, consumer group migration, or automatic topic configuration sync across clusters. MirrorMaker 2 was built on Kafka Connect to address these gaps.",
        "answer_type": "decision",
        "difficulty": "hard",
        "topic": "mirrormaker",
    },
    {
        "question": "Why does Kafka use a binary protocol instead of HTTP?",
        "expected_answer": "A binary protocol is more compact and faster to serialize/deserialize than HTTP/JSON, which is critical for Kafka's high-throughput, low-latency requirements.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "protocol",
    },
    {
        "question": "Why was the Kafka Streams DSL introduced?",
        "expected_answer": "The Streams DSL provides a higher-level functional API for common stream processing patterns like map, filter, join, and aggregate, reducing boilerplate compared to the Processor API.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "kafka streams",
    },
    {
        "question": "Why does Kafka batch messages at both producer and consumer?",
        "expected_answer": "Batching amortizes the cost of network round trips and disk I/O operations across multiple messages, dramatically increasing throughput at the cost of slight latency increase.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "producer",
    },
    {
        "question": "Why was Schema Registry not included in the core Kafka project?",
        "expected_answer": "Schema Registry was kept as a separate component to avoid coupling schema management to the core broker, allowing different implementations and keeping the broker lightweight.",
        "answer_type": "decision",
        "difficulty": "hard",
        "topic": "schema registry",
    },
    {
        "question": "Why does Kafka use topic partitions for parallelism instead of threads?",
        "expected_answer": "Partitions distribute load across brokers and allow parallel consumption by multiple consumers. Thread-based parallelism within a single broker would limit scalability to one machine.",
        "answer_type": "decision",
        "difficulty": "medium",
        "topic": "partition",
    },
    {
        "question": "Why did Kafka introduce transaction support?",
        "expected_answer": "Transactions allow producers to write to multiple partitions atomically, enabling exactly-once stream processing where consuming, processing, and producing all happen as one atomic unit.",
        "answer_type": "decision",
        "difficulty": "hard",
        "topic": "transactions",
    },

    # ── EXPERT questions (10) ─────────────────────────────────────
    {
        "question": "Who are the key contributors to the KRaft implementation in Kafka?",
        "expected_answer": "Key contributors include Colin McCabe, Jason Gustafson, and Jun Rao who drove the KIP-500 proposal and implementation.",
        "answer_type": "expert",
        "difficulty": "hard",
        "topic": "kraft",
    },
    {
        "question": "Who should I contact to understand Kafka's replication protocol?",
        "expected_answer": "Jun Rao and Jason Gustafson are the most knowledgeable contributors on Kafka's replication protocol based on their decision involvement and document mentions.",
        "answer_type": "expert",
        "difficulty": "medium",
        "topic": "replication",
    },
    {
        "question": "Who originally proposed tiered storage for Kafka?",
        "expected_answer": "Satish Duggana and Adem Efe Gencer were among the primary contributors to tiered storage KIPs in Apache Kafka.",
        "answer_type": "expert",
        "difficulty": "hard",
        "topic": "tiered storage",
    },
    {
        "question": "Who are the main experts on Kafka Streams?",
        "expected_answer": "Matthias J. Sax is the primary expert on Kafka Streams, having authored multiple KIPs and led the Streams development.",
        "answer_type": "expert",
        "difficulty": "medium",
        "topic": "kafka streams",
    },
    {
        "question": "Who has been most active in Kafka security discussions?",
        "expected_answer": "Rajini Sivaram has been heavily involved in Kafka security, SSL/TLS, and authentication KIPs.",
        "answer_type": "expert",
        "difficulty": "hard",
        "topic": "security",
    },
    {
        "question": "Who should I ask about Kafka consumer group internals?",
        "expected_answer": "Jason Gustafson and Guozhang Wang are key experts on consumer group coordination and the group coordinator protocol.",
        "answer_type": "expert",
        "difficulty": "medium",
        "topic": "consumer group",
    },
    {
        "question": "Who are the founding contributors of Apache Kafka?",
        "expected_answer": "Kafka was originally created at LinkedIn by Jay Kreps, Neha Narkhede, and Jun Rao before being open-sourced as an Apache project.",
        "answer_type": "expert",
        "difficulty": "easy",
        "topic": "kafka history",
    },
    {
        "question": "Who drove the exactly-once semantics implementation in Kafka?",
        "expected_answer": "Apurva Mehta and Jason Gustafson were primary contributors to the exactly-once semantics and idempotent producer implementation.",
        "answer_type": "expert",
        "difficulty": "hard",
        "topic": "exactly once",
    },
    {
        "question": "Who should I talk to about Kafka Connect architecture?",
        "expected_answer": "Randall Hauch and Arjun Satish are key contributors to Kafka Connect, having designed and implemented core parts of the framework.",
        "answer_type": "expert",
        "difficulty": "medium",
        "topic": "kafka connect",
    },
    {
        "question": "Who are the main contributors to MirrorMaker 2?",
        "expected_answer": "A. Sophie Blee-Goldman and Ryanne Dolan were primary contributors to MirrorMaker 2 design and implementation.",
        "answer_type": "expert",
        "difficulty": "hard",
        "topic": "mirrormaker",
    },
]


def load_eval_questions():
    """
    Inserts all seed questions into the eval_questions table.
    Safe to run multiple times — skips duplicates via ON CONFLICT DO NOTHING.
    """
    conn = get_connection()
    cursor = conn.cursor()

    inserted = 0
    skipped = 0

    for q in SEED_QUESTIONS:
        try:
            cursor.execute("""
                INSERT INTO eval_questions
                    (question, expected_answer, answer_type, difficulty, topic)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id;
            """, (
                q["question"],
                q["expected_answer"],
                q["answer_type"],
                q["difficulty"],
                q["topic"],
            ))

            result = cursor.fetchone()
            if result:
                inserted += 1
            else:
                skipped += 1

        except Exception as e:
            logger.error(f"Failed to insert question: {q['question'][:50]} — {e}")
            conn.rollback()

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"Eval questions loaded: {inserted} inserted | {skipped} skipped")
    return {"inserted": inserted, "skipped": skipped}


def print_eval_summary():
    """Prints a breakdown of your eval dataset."""
    conn = get_connection()
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("EVAL DATASET SUMMARY")
    print("=" * 60)

    cursor.execute("""
        SELECT answer_type, difficulty, COUNT(*)
        FROM eval_questions
        GROUP BY answer_type, difficulty
        ORDER BY answer_type, difficulty;
    """)

    rows = cursor.fetchall()
    current_type = None

    for answer_type, difficulty, count in rows:
        if answer_type != current_type:
            print(f"\n[{answer_type.upper()}] questions")
            current_type = answer_type
        print(f"   {difficulty:<10} {count} questions")

    cursor.execute("SELECT COUNT(*) FROM eval_questions;")
    total = cursor.fetchone()[0]
    print(f"\nTotal: {total} questions")
    print("=" * 60)

    cursor.close()
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    result = load_eval_questions()
    print_eval_summary()
